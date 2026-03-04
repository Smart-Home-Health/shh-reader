from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseDevice(ABC):
    name: str = ""
    slug: str = ""
    supported_connections: list[str] = []
    default_baud_rate: int = 115200

    @abstractmethod
    def parse_line(self, raw: str) -> dict[str, Any] | None: ...
