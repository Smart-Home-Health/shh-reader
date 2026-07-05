from __future__ import annotations

from db import apply_to_state, load_settings, save_settings
from app_state import state


def test_load_empty_db_returns_empty():
    assert load_settings() == {}


def test_apply_to_state_empty_db_is_noop():
    assert apply_to_state(state) is False
    assert state.device_type is None


def test_save_load_round_trip():
    state.device_type = "pm1000n"
    state.connection_mode = "lan"
    state.lan_listen_port = 6001
    state.host_ws_url = "ws://192.168.1.5:8000/api/readers/ws/3"
    state.encryption_key = "abc123"
    state.reader_id = 3
    state.is_paired = True
    state.mqtt_enabled = True
    state.mqtt_broker = "192.168.1.9"

    save_settings(state)
    saved = load_settings()

    assert saved["device_type"] == "pm1000n"
    assert saved["connection_mode"] == "lan"
    assert saved["lan_listen_port"] == 6001
    assert saved["host_ws_url"] == "ws://192.168.1.5:8000/api/readers/ws/3"
    assert saved["encryption_key"] == "abc123"
    assert saved["reader_id"] == 3
    assert saved["is_paired"] is True
    assert saved["mqtt_enabled"] is True
    assert saved["mqtt_broker"] == "192.168.1.9"


def test_auto_start_tracks_is_running():
    state.is_running = True
    save_settings(state)
    assert load_settings()["auto_start"] is True

    state.is_running = False
    save_settings(state)
    assert load_settings()["auto_start"] is False


def test_apply_to_state_restores_settings_and_returns_auto_start():
    state.device_type = "pm1000n"
    state.connection_mode = "usb"
    state.usb_port = "/dev/ttyUSB0"
    state.baud_rate = 9600
    state.is_running = True
    save_settings(state)

    # Fresh boot: wipe in-memory state, then load from DB
    state.device_type = None
    state.connection_mode = None
    state.usb_port = None
    state.baud_rate = 115200
    state.is_running = False

    assert apply_to_state(state) is True
    assert state.device_type == "pm1000n"
    assert state.connection_mode == "usb"
    assert state.usb_port == "/dev/ttyUSB0"
    assert state.baud_rate == 9600
    # auto_start is reported, not applied — main.py decides whether to start
    assert state.is_running is False


def test_apply_to_state_skips_none_values():
    # usb_port was never configured (None) — a later load must not
    # clobber an in-memory value with None.
    save_settings(state)  # persists usb_port=None
    state.usb_port = "/dev/ttyUSB1"
    apply_to_state(state)
    assert state.usb_port == "/dev/ttyUSB1"


def test_save_is_idempotent_upsert():
    state.device_name = "reader-one"
    save_settings(state)
    state.device_name = "reader-two"
    save_settings(state)
    assert load_settings()["device_name"] == "reader-two"
