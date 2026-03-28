from __future__ import annotations

import asyncio
import collections
import random
import string
from dataclasses import dataclass, field
from typing import Any

from cryptography.fernet import Fernet


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
    pending_pair_code: str | None = None
    device_name: str = "shh-reader"

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

    reader_task: asyncio.Task | None = field(default=None, repr=False)
    ws_task: asyncio.Task | None = field(default=None, repr=False)
    mqtt_task: asyncio.Task | None = field(default=None, repr=False)
    diagnostic_subscribers: list[Any] = field(default_factory=list)

    def fernet(self) -> Fernet | None:
        if self.encryption_key:
            return Fernet(self.encryption_key.encode())
        return None

    def generate_pair_code(self) -> str:
        code = "".join(random.choices(string.digits, k=6))
        self.pending_pair_code = code
        return code

    def clear_pairing(self) -> None:
        self.host_ws_url = None
        self.encryption_key = None
        self.reader_id = None
        self.is_paired = False
        self.pending_pair_code = None

    def config_summary(self) -> dict:
        return {
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
