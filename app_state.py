from __future__ import annotations

import asyncio
import collections
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from cryptography.fernet import Fernet

# Pending pairing requests expire after this many seconds without a response.
PENDING_PAIR_TTL = 180


@dataclass
class PendingPair:
    """In-flight pairing request from a hub. Memory-only — never persisted;
    a reader restart simply expires the request and the hub retries."""
    hub_public_key: str
    host_ws_url: str
    reader_id: int | None
    caller_ip: str | None
    requested_at: float  # time.monotonic()
    status: str = "pending"  # pending | approved | denied
    reader_public_key: str | None = None

    def expired(self) -> bool:
        return time.monotonic() - self.requested_at > PENDING_PAIR_TTL


@dataclass
class AppState:
    device_type: str | None = None
    connection_mode: str | None = None
    usb_port: str | None = None
    baud_rate: int = 115200
    lan_listen_port: int = 5001

    host_ws_url: str | None = None
    encryption_key: str | None = None
    reader_id: int | None = None
    is_paired: bool = False
    pending_pair: PendingPair | None = None
    device_name: str = "shh-reader"

    # Per-boot token injected into the reader's own dashboard page so it can
    # keep reading live vitals before a hub is paired. Soft gating, not auth:
    # anyone who can load the page can extract it (same LAN trust level as
    # the rest of the API).
    ui_token: str = field(default_factory=lambda: secrets.token_urlsafe(16))

    # MQTT optional output
    mqtt_enabled: bool = False
    mqtt_broker: str = ""
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_topic1: str = ""
    mqtt_topic2: str = ""
    mqtt_topic3: str = ""
    mqtt_client_id: str = "shh-reader"

    is_running: bool = False
    raw_buffer: collections.deque = field(
        default_factory=lambda: collections.deque(maxlen=100)
    )
    data_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    mqtt_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    latest_values: dict = field(default_factory=lambda: {
        "spo2": None, "spo2_alarm": False,
        "bpm": None, "bpm_alarm": False,
        "perfusion": None,
    })

    ws_state: str = "disconnected"       # disconnected | connecting | connected | retrying
    ws_last_error: str | None = None
    ws_connected_since: str | None = None

    reader_task: asyncio.Task | None = field(default=None, repr=False)
    ws_task: asyncio.Task | None = field(default=None, repr=False)
    mqtt_task: asyncio.Task | None = field(default=None, repr=False)
    diagnostic_subscribers: list[Any] = field(default_factory=list)

    def fernet(self) -> Fernet | None:
        if self.encryption_key:
            return Fernet(self.encryption_key.encode())
        return None

    def active_pending_pair(self) -> PendingPair | None:
        """Return the pending pairing request, lazily expiring stale ones."""
        if self.pending_pair and self.pending_pair.expired():
            self.pending_pair = None
        return self.pending_pair

    def clear_pairing(self) -> None:
        self.host_ws_url = None
        self.encryption_key = None
        self.reader_id = None
        self.is_paired = False
        self.pending_pair = None

    def config_summary(self) -> dict:
        pending = self.active_pending_pair()
        return {
            "pending_pair": (
                {"hub_ip": pending.caller_ip}
                if pending and pending.status == "pending"
                else None
            ),
            "device_type": self.device_type,
            "connection_mode": self.connection_mode,
            "usb_port": self.usb_port,
            "baud_rate": self.baud_rate,
            "lan_listen_port": self.lan_listen_port,
            "host_ws_url": self.host_ws_url,
            "reader_id": self.reader_id,
            "is_paired": self.is_paired,
            "is_running": self.is_running,
            "device_name": self.device_name,
            "mqtt_enabled": self.mqtt_enabled,
            "mqtt_broker": self.mqtt_broker,
            "mqtt_port": self.mqtt_port,
            "mqtt_username": self.mqtt_username,
            "mqtt_password": self.mqtt_password,
            "mqtt_topic1": self.mqtt_topic1,
            "mqtt_topic2": self.mqtt_topic2,
            "mqtt_topic3": self.mqtt_topic3,
            "mqtt_client_id": self.mqtt_client_id,
        }


# Module-level singleton — imported everywhere
state = AppState()
