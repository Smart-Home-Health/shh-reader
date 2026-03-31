from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import serial
import serial.tools.list_ports

from .base import BaseConnection


class USBSerialConnection(BaseConnection):

    def __init__(self, port: str, baud_rate: int = 115200):
        self.port = port
        self.baud_rate = baud_rate
        self._ser: serial.Serial | None = None
        self._stop = False

    async def connect(self) -> None:
        self._stop = False
        self._ser = await asyncio.to_thread(
            serial.Serial, self.port, self.baud_rate, timeout=1
        )

    async def disconnect(self) -> None:
        self._stop = True
        if self._ser and self._ser.is_open:
            await asyncio.to_thread(self._ser.close)
            self._ser = None

    async def read_lines(self) -> AsyncGenerator[str, None]:
        assert self._ser is not None, "Call connect() first"
        while not self._stop:
            raw: bytes = await asyncio.to_thread(self._ser.readline)
            if raw:
                yield raw.decode(errors="ignore").strip()

    @staticmethod
    def list_ports() -> list[dict]:
        return [
            {
                "device": p.device,
                "description": p.description,
                "manufacturer": p.manufacturer or "",
            }
            for p in serial.tools.list_ports.comports()
        ]
