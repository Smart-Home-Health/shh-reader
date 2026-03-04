from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app_state import state
from db import save_settings
from devices import get_device, list_devices
from connections import USBSerialConnection, LANTCPConnection
from transport.ws_client import ws_sender_loop

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class ConfigPayload(BaseModel):
    device_type: str
    connection_mode: str
    usb_port: str | None = None
    baud_rate: int | None = None
    lan_listen_port: int | None = None


class PairPayload(BaseModel):
    host_url: str          # ws://host:port/api/readers/ws/{id}
    encryption_key: str    # base64-encoded Fernet key


class ConfirmPairPayload(BaseModel):
    code: str


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


@router.post("/pair")
async def api_pair(body: PairPayload):
    state.host_ws_url = body.host_url
    state.encryption_key = body.encryption_key
    code = state.generate_pair_code()
    save_settings(state)
    return {
        "code": code,
        "device_name": state.device_name,
    }


@router.post("/pair/confirm")
async def api_confirm_pair(body: ConfirmPairPayload):
    if state.pending_pair_code is None:
        raise HTTPException(400, "No pending pairing")
    if body.code != state.pending_pair_code:
        raise HTTPException(400, "Code mismatch")
    state.is_paired = True
    state.pending_pair_code = None
    save_settings(state)
    return {"ok": True, "is_paired": True}


@router.post("/unpair")
async def api_unpair():
    await _stop_tasks()
    state.clear_pairing()
    save_settings(state)
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
    log.info("Starting reader (%s / %s)", state.device_type, state.connection_mode)
    state.reader_task = asyncio.create_task(_reader_loop())

    if state.is_paired and state.host_ws_url:
        state.ws_task = asyncio.create_task(ws_sender_loop())
        log.info("WS sender started")
    else:
        log.info("Not paired — reader running for diagnostics only")

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
        log.info("Reader: stopped")


async def _stop_tasks() -> None:
    state.is_running = False
    for task in (state.reader_task, state.ws_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    state.reader_task = None
    state.ws_task = None
