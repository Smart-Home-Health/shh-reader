from __future__ import annotations

from .base import BaseDevice
from .pm100n import PM100N
from .pm1000n import PM1000N

DEVICE_REGISTRY: dict[str, BaseDevice] = {
    PM100N.slug: PM100N(),
    PM1000N.slug: PM1000N(),
}


def get_device(slug: str) -> BaseDevice | None:
    return DEVICE_REGISTRY.get(slug)


def list_devices() -> list[dict]:
    return [
        {
            "slug": d.slug,
            "name": d.name,
            "supported_connections": d.supported_connections,
            "default_baud_rate": d.default_baud_rate,
        }
        for d in DEVICE_REGISTRY.values()
    ]
