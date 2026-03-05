from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app_state import state
from db import save_settings
from devices import get_device, list_devices
from connections import USBSerialConnection, LANTCPConnection
from transport.ws_client import ws_sender_loop
from transport.mqtt_client import mqtt_publisher_loop

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class ConfigPayload(BaseModel):
    device_type: str
    connection_mode: str
    usb_port: str | None = None
    baud_rate: int | None = None
    lan_listen_port: int | None = None


class PairPayload(BaseModel):
    host_url: str
    encryption_key: str


class ConfirmPairPayload(BaseModel):
    code: str
    host_url: str | None = None
    encryption_key: str | None = None


class MqttConfigPayload(BaseModel):
    mqtt_enabled: bool = False
    mqtt_broker: str = ""
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_topic1: str = ""
    mqtt_topic2: str = ""
    mqtt_client_id: str = "shh-reader"


@router.get("/devices")
async def api_list_devices():
    return list_devices()


@router.get("/ports")
async def api_list_ports():
    return USBSerialConnection.list_ports()


@router.get("/config")
async def api_get_config():
    return state.config_summary()


@router.post("/config")
async def api_set_config(body: ConfigPayload):
    device = get_device(body.device_type)
    if device is None:
        raise HTTPException(400, f"Unknown device: {body.device_type}")

    if body.connection_mode not in device.supported_connections:
        raise HTTPException(400, f"{device.name} does not support '{body.connection_mode}'")

    state.device_type = body.device_type
    state.connection_mode = body.connection_mode

    if body.connection_mode == "usb":
        if body.usb_port:
            state.usb_port = body.usb_port
        state.baud_rate = body.baud_rate or device.default_baud_rate
    elif body.connection_mode == "lan":
        state.lan_listen_port = body.lan_listen_port or 5001

    save_settings(state)
    return {"ok": True, **state.config_summary()}


@router.post("/mqtt")
async def api_set_mqtt(body: MqttConfigPayload):
    was_enabled = state.mqtt_enabled
    state.mqtt_enabled = body.mqtt_enabled
    state.mqtt_broker = body.mqtt_broker
    state.mqtt_port = body.mqtt_port
    state.mqtt_username = body.mqtt_username
    state.mqtt_password = body.mqtt_password
    state.mqtt_topic1 = body.mqtt_topic1
    state.mqtt_topic2 = body.mqtt_topic2
    state.mqtt_client_id = body.mqtt_client_id
    save_settings(state)
    log.info("MQTT-CFG: enabled=%s broker=%s:%s topics=%s,%s",
             state.mqtt_enabled, state.mqtt_broker, state.mqtt_port,
             state.mqtt_topic1, state.mqtt_topic2)

    # If reader is running, manage the MQTT task
    if state.is_running:
        if state.mqtt_enabled and (state.mqtt_task is None or state.mqtt_task.done()):
            state.mqtt_task = asyncio.create_task(mqtt_publisher_loop())
            log.info("MQTT-CFG: started MQTT publisher (reader already running)")
        elif not state.mqtt_enabled and state.mqtt_task and not state.mqtt_task.done():
            state.mqtt_task.cancel()
            try:
                await state.mqtt_task
            except asyncio.CancelledError:
                pass
            state.mqtt_task = None
            log.info("MQTT-CFG: stopped MQTT publisher")

    return {"ok": True, **state.config_summary()}


def _extract_reader_id(ws_url: str) -> int | None:
    try:
        parts = ws_url.rstrip("/").split("/")
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


def _fix_ws_url(ws_url: str, real_ip: str) -> str:
    """Replace unresolvable docker-internal hostnames with the caller's real IP."""
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(ws_url)
    host = parsed.hostname or ""
    if "docker.internal" in host or "localhost" in host or host == "127.0.0.1":
        new_netloc = f"{real_ip}:{parsed.port}" if parsed.port else real_ip
        fixed = urlunparse(parsed._replace(netloc=new_netloc))
        log.info("PAIR: rewrote WS URL %s → %s (caller IP %s)", ws_url, fixed, real_ip)
        return fixed
    return ws_url


@router.post("/pair")
async def api_pair(body: PairPayload, request: Request):
    caller_ip = request.client.host if request.client else None
    log.info("PAIR: received host_url=%s from %s", body.host_url, caller_ip)
    log.info("PAIR: encryption_key=%s...", body.encryption_key[:12] if body.encryption_key else "NONE")
    ws_url = body.host_url
    if caller_ip:
        ws_url = _fix_ws_url(ws_url, caller_ip)
    state.host_ws_url = ws_url
    state.encryption_key = body.encryption_key
    state.reader_id = _extract_reader_id(ws_url)
    log.info("PAIR: extracted reader_id=%s from URL", state.reader_id)
    code = state.generate_pair_code()
    log.info("PAIR: generated code=%s", code)
    save_settings(state)
    log.info("PAIR: settings saved, returning code + device_name=%s", state.device_name)
    return {
        "code": code,
        "device_name": state.device_name,
    }


@router.post("/pair/confirm")
async def api_confirm_pair(body: ConfirmPairPayload):
    log.info("PAIR-CONFIRM: code=%s, host_url=%s, has_key=%s",
             body.code, body.host_url, bool(body.encryption_key))
    log.info("PAIR-CONFIRM: pending_code=%s, is_paired=%s, reader_id=%s",
             state.pending_pair_code, state.is_paired, state.reader_id)
    if state.pending_pair_code is None:
        log.warning("PAIR-CONFIRM: REJECTED — no pending code")
        raise HTTPException(400, "No pending pairing")
    if body.code != state.pending_pair_code:
        log.warning("PAIR-CONFIRM: REJECTED — code mismatch (got %s, want %s)",
                    body.code, state.pending_pair_code)
        raise HTTPException(400, "Code mismatch")
    if body.host_url and body.host_url != state.host_ws_url:
        log.info("PAIR-CONFIRM: updating host_ws_url from %s to %s",
                 state.host_ws_url, body.host_url)
        state.host_ws_url = body.host_url
        state.reader_id = _extract_reader_id(body.host_url)
    state.is_paired = True
    state.pending_pair_code = None
    save_settings(state)
    log.info("PAIR-CONFIRM: SUCCESS — is_paired=%s, reader_id=%s, host_ws_url=%s",
             state.is_paired, state.reader_id, state.host_ws_url)

    # If reader is already running but WS sender wasn't started, start it now
    if state.is_running and state.host_ws_url and (state.ws_task is None or state.ws_task.done()):
        state.ws_task = asyncio.create_task(ws_sender_loop())
        log.info("PAIR-CONFIRM: started WS sender (reader was already running)")

    return {"success": True, "is_paired": True}


@router.post("/unpair")
async def api_unpair():
    log.info("UNPAIR: clearing pairing (was reader_id=%s, paired=%s)",
             state.reader_id, state.is_paired)
    await _stop_tasks()
    state.clear_pairing()
    save_settings(state)
    log.info("UNPAIR: done")
    return {"ok": True}


@router.post("/start")
async def api_start():
    if state.is_running:
        raise HTTPException(400, "Already running")
    if not state.device_type or not state.connection_mode:
        raise HTTPException(400, "Configure device and connection first")
    await _start_reader()
    return {"ok": True, "is_running": True}


async def _start_reader():
    state.is_running = True
    log.info("START: device=%s, conn=%s, paired=%s, reader_id=%s",
             state.device_type, state.connection_mode, state.is_paired, state.reader_id)
    log.info("START: host_ws_url=%s", state.host_ws_url)
    state.reader_task = asyncio.create_task(_reader_loop())

    if state.is_paired and state.host_ws_url:
        state.ws_task = asyncio.create_task(ws_sender_loop())
        log.info("START: WS sender task created")
    else:
        log.info("START: no WS sender (paired=%s, url=%s)",
                 state.is_paired, state.host_ws_url)

    if state.mqtt_enabled and state.mqtt_broker:
        state.mqtt_task = asyncio.create_task(mqtt_publisher_loop())
        log.info("START: MQTT publisher task created")

    save_settings(state)


@router.post("/stop")
async def api_stop():
    await _stop_tasks()
    save_settings(state)
    return {"ok": True, "is_running": False}


@router.get("/latest")
async def api_latest():
    return state.latest_values


@router.get("/diagnostics")
async def api_diagnostics():
    return {"lines": list(state.raw_buffer)}


@router.websocket("/diagnostics/ws")
async def ws_diagnostics(ws: WebSocket):
    await ws.accept()
    state.diagnostic_subscribers.append(ws)
    try:
        while True:
            # Keep connection alive; client won't send much
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state.diagnostic_subscribers.remove(ws)


async def _broadcast_raw(line: str) -> None:
    dead = []
    for ws in state.diagnostic_subscribers:
        try:
            await ws.send_text(line)
        except Exception:
            dead.append(ws)
    for ws in dead:
        state.diagnostic_subscribers.remove(ws)


async def _reader_loop() -> None:
    device = get_device(state.device_type)
    if device is None:
        log.error("No device selected")
        return

    if state.connection_mode == "usb":
        if not state.usb_port:
            log.error("No USB port configured")
            return
        conn = USBSerialConnection(state.usb_port, state.baud_rate)
    elif state.connection_mode == "lan":
        conn = LANTCPConnection(listen_port=state.lan_listen_port)
    else:
        log.error("Unknown connection mode: %s", state.connection_mode)
        return

    try:
        await conn.connect()
        log.info("Reader: connection open (%s)", state.connection_mode)

        async for line in conn.read_lines():
            if not state.is_running:
                break

            state.raw_buffer.append(line)
            await _broadcast_raw(line)
            log.info("Raw: %s", line)

            parsed = device.parse_line(line)
            if parsed is None:
                continue

            state.latest_values = parsed
            await state.data_queue.put(parsed)

            # Also feed MQTT queue if enabled
            if state.mqtt_enabled:
                await state.mqtt_queue.put(parsed)

            log.info(
                "Parsed: SpO2=%s%s  BPM=%s%s  PA=%s",
                parsed["spo2"],
                "*" if parsed["spo2_alarm"] else "",
                parsed["bpm"],
                "*" if parsed["bpm_alarm"] else "",
                parsed["perfusion"],
            )

    except asyncio.CancelledError:
        log.info("Reader: cancelled")
    except Exception as exc:
        log.exception("Reader error: %s", exc)
    finally:
        await conn.disconnect()
        state.is_running = False
        state.latest_values = {
            "spo2": -1, "spo2_alarm": False,
            "bpm": -1, "bpm_alarm": False,
            "perfusion": -1,
        }
        log.info("Reader: stopped")


async def _stop_tasks() -> None:
    state.is_running = False
    for task in (state.reader_task, state.ws_task, state.mqtt_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    state.reader_task = None
    state.ws_task = None
    state.mqtt_task = None
