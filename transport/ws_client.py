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
    f = state.fernet()
    if f is None:
        log.warning("WS-SEND: no encryption key — skipping %s", payload.get("type"))
        return
    raw = json.dumps(payload).encode()
    token = f.encrypt(raw)
    log.info("WS-SEND: type=%s  plaintext=%d bytes  encrypted=%d bytes",
             payload.get("type"), len(raw), len(token))
    await ws.send(token)
    log.info("WS-SEND: sent OK")


async def ws_sender_loop() -> None:
    backoff = RECONNECT_BASE

    while state.is_running:
        url = state.host_ws_url
        if not url:
            log.warning("No host WebSocket URL configured — waiting…")
            await asyncio.sleep(5)
            continue

        log.info("WS: connecting to %s (reader_id=%s, paired=%s)",
                 url, state.reader_id, state.is_paired)
        state.ws_state = "connecting"
        try:
            async with websockets.connect(url) as ws:
                log.info("WS: connected to %s", url)
                backoff = RECONNECT_BASE
                state.ws_state = "connected"
                state.ws_last_error = None
                state.ws_connected_since = datetime.now(timezone.utc).isoformat()

                handshake = {
                    "type": "handshake",
                    "device_name": state.device_name,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
                log.info("WS: sending handshake: %s", handshake)
                await _send_encrypted(ws, handshake)

                listener = asyncio.create_task(_ws_listener(ws))
                pinger = asyncio.create_task(_ws_pinger(ws))

                log.info("WS: connected — entering send loop (queue size=%d)", state.data_queue.qsize())

                try:
                    while state.is_running:
                        try:
                            data = await asyncio.wait_for(
                                state.data_queue.get(), timeout=1.0
                            )
                        except asyncio.TimeoutError:
                            continue

                        log.info("WS: dequeued data: %s (queue remaining=%d)", data, state.data_queue.qsize())
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
            state.ws_state = "retrying"
            state.ws_last_error = str(exc)
            state.ws_connected_since = None
            log.warning("WS: connection error: %s — retrying in %ds", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_MAX)

        except asyncio.CancelledError:
            log.info("WS: sender task cancelled")
            state.ws_state = "disconnected"
            state.ws_connected_since = None
            return

    state.ws_state = "disconnected"
    state.ws_connected_since = None
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
                log.info("WS recv: %s", msg)
            except Exception as e:
                log.warning("WS recv decrypt/parse failed: %s — raw[:120]=%s", e, raw[:120])
    except asyncio.CancelledError:
        return
    except websockets.exceptions.ConnectionClosed:
        return


async def _ws_pinger(ws) -> None:
    try:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            log.info("WS-PING: sending keepalive")
            await _send_encrypted(ws, {
                "type": "ping",
            })
    except asyncio.CancelledError:
        return
    except websockets.exceptions.ConnectionClosed:
        return
