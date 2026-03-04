from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import websockets
import websockets.exceptions

from app_state import state

log = logging.getLogger(__name__)

RECONNECT_BASE = 2       # seconds
RECONNECT_MAX = 30        # cap
PING_INTERVAL = 25        # seconds between keepalive pings


async def _send_encrypted(ws, payload: dict) -> None:
    """Encrypt a dict and send as a binary frame."""
    f = state.fernet()
    if f is None:
        log.warning("No encryption key — skipping send")
        return
    raw = json.dumps(payload).encode()
    token = f.encrypt(raw)
    await ws.send(token)


async def ws_sender_loop() -> None:
    backoff = RECONNECT_BASE

    while state.is_running:
        url = state.host_ws_url
        if not url:
            log.warning("No host WebSocket URL configured — waiting…")
            await asyncio.sleep(5)
            continue

        try:
            async with websockets.connect(url) as ws:
                log.info("WS: connected to %s", url)
                backoff = RECONNECT_BASE

                await _send_encrypted(ws, {
                    "type": "handshake",
                    "device_name": state.device_name,
                    "ts": datetime.now(timezone.utc).isoformat(),
                })

                listener = asyncio.create_task(_ws_listener(ws))
                pinger = asyncio.create_task(_ws_pinger(ws))

                try:
                    while state.is_running:
                        try:
                            data = await asyncio.wait_for(
                                state.data_queue.get(), timeout=1.0
                            )
                        except asyncio.TimeoutError:
                            continue

                        ts = datetime.now(timezone.utc).isoformat()
                        msg = {
                            "type": "sensor",
                            "ts": ts,
                            "values": {
                                "spo2": data.get("spo2", -1),
                                "bpm": data.get("bpm", -1),
                                "perfusion": data.get("perfusion", 0),
                            },
                        }
                        await _send_encrypted(ws, msg)
                        log.info("WS: sent sensor data")

                        if data.get("spo2_alarm") or data.get("bpm_alarm"):
                            alarm_msg = {
                                "type": "alarm",
                                "ts": ts,
                                "alarm1": data.get("spo2_alarm", False),
                                "alarm2": data.get("bpm_alarm", False),
                            }
                            await _send_encrypted(ws, alarm_msg)
                            log.info("WS: sent alarm")

                finally:
                    listener.cancel()
                    pinger.cancel()

        except (
            OSError,
            websockets.exceptions.WebSocketException,
            ConnectionError,
        ) as exc:
            log.warning("WS: connection error: %s — retrying in %ds", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_MAX)

        except asyncio.CancelledError:
            log.info("WS: sender task cancelled")
            return

    log.info("WS: sender stopped (is_running=False)")


async def _ws_listener(ws) -> None:
    try:
        async for raw in ws:
            try:
                f = state.fernet()
                if f:
                    msg = json.loads(f.decrypt(raw))
                else:
                    msg = json.loads(raw)
                log.debug("WS recv: %s", msg)
            except Exception:
                log.debug("WS recv (non-JSON): %s", raw[:120])
    except asyncio.CancelledError:
        return
    except websockets.exceptions.ConnectionClosed:
        return


async def _ws_pinger(ws) -> None:
    try:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            await _send_encrypted(ws, {
                "type": "ping",
            })
    except asyncio.CancelledError:
        return
    except websockets.exceptions.ConnectionClosed:
        return
