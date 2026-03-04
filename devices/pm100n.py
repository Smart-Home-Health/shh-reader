from __future__ import annotations

import re
from typing import Any

from .base import BaseDevice

_LINE_RE = re.compile(
    r"\d{2}-\w{3}-\d{2}\s+\d{2}:\d{2}:\d{2}"
    r"\s+([\d]{2,3}\*?|---)"
    r"\s+([\d]{2,3}\*?|---)"
    r"\s+(\d+)"
)


class PM100N(BaseDevice):
    name = "Mindray PM-100N"
    slug = "pm100n"
    supported_connections = ["usb"]
    default_baud_rate = 115200

    def parse_line(self, raw: str) -> dict[str, Any] | None:
        m = _LINE_RE.search(raw)
        if not m:
            return None

        spo2_raw, bpm_raw, pa_raw = m.group(1), m.group(2), m.group(3)

        if spo2_raw == "---" or bpm_raw == "---":
            return None

        return {
            "spo2": int(spo2_raw.rstrip("*")),
            "spo2_alarm": spo2_raw.endswith("*"),
            "bpm": int(bpm_raw.rstrip("*")),
            "bpm_alarm": bpm_raw.endswith("*"),
            "perfusion": int(pa_raw),
        }
