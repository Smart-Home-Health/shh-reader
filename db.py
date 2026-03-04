from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "shh_reader.db"

_PERSISTED_KEYS = [
    "device_type", "connection_mode", "usb_port", "baud_rate",
    "lan_listen_port", "host_ws_url", "encryption_key", "reader_id",
    "is_paired", "device_name", "auto_start",
]


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    return c


def save_settings(state) -> None:
    c = _conn()
    try:
        rows = []
        for k in _PERSISTED_KEYS:
            if k == "auto_start":
                rows.append((k, json.dumps(state.is_running)))
            else:
                rows.append((k, json.dumps(getattr(state, k, None))))
        c.executemany(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", rows
        )
        c.commit()
    finally:
        c.close()


def load_settings() -> dict:
    c = _conn()
    try:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
        out = {}
        for k, v in rows:
            out[k] = json.loads(v)
        return out
    finally:
        c.close()


def apply_to_state(state) -> bool:
    """Load persisted settings into state. Returns True if auto_start was set."""
    saved = load_settings()
    if not saved:
        return False

    for k in _PERSISTED_KEYS:
        if k == "auto_start":
            continue
        if k in saved and saved[k] is not None:
            setattr(state, k, saved[k])

    return saved.get("auto_start", False)
