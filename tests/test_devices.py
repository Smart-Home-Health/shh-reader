from __future__ import annotations

import pytest

from devices import DEVICE_REGISTRY, get_device, list_devices
from devices.pm100n import PM100N
from devices.pm1000n import PM1000N

# Both Mindray models emit the same serial line format:
#   DD-MMM-YY HH:MM:SS  <spo2>[*]  <bpm>[*]  <perfusion>
# where "*" marks an active alarm and "---" means no finger / no reading.
DEVICES = [PM100N(), PM1000N()]


@pytest.mark.parametrize("device", DEVICES, ids=lambda d: d.slug)
class TestParseLine:
    def test_normal_reading(self, device):
        parsed = device.parse_line("05-Jul-26 10:15:00  98  72  120")
        assert parsed == {
            "spo2": 98, "spo2_alarm": False,
            "bpm": 72, "bpm_alarm": False,
            "perfusion": 120,
        }

    def test_alarm_flags(self, device):
        parsed = device.parse_line("05-Jul-26 10:15:01  88*  130*  45")
        assert parsed["spo2"] == 88
        assert parsed["spo2_alarm"] is True
        assert parsed["bpm"] == 130
        assert parsed["bpm_alarm"] is True

    def test_single_alarm(self, device):
        parsed = device.parse_line("05-Jul-26 10:15:02  91*  70  80")
        assert parsed["spo2_alarm"] is True
        assert parsed["bpm_alarm"] is False

    def test_no_reading_sentinel(self, device):
        # Sensor off the finger: both channels report "---"
        parsed = device.parse_line("05-Jul-26 10:15:03  ---  ---  0")
        assert parsed == {
            "spo2": -1, "spo2_alarm": False,
            "bpm": -1, "bpm_alarm": False,
            "perfusion": -1,
        }

    def test_partial_sentinel_is_sentinel(self, device):
        # Either channel missing means the whole reading is unusable
        parsed = device.parse_line("05-Jul-26 10:15:04  ---  72  10")
        assert parsed["spo2"] == -1
        assert parsed["bpm"] == -1

    def test_garbage_returns_none(self, device):
        assert device.parse_line("") is None
        assert device.parse_line("boot banner: PM series v1.2") is None
        assert device.parse_line("98 72 120") is None  # no timestamp prefix

    def test_line_with_surrounding_noise(self, device):
        # parse_line uses search(), so leading junk is tolerated
        parsed = device.parse_line("\x0205-Jul-26 10:15:05  97  65  110\r")
        assert parsed["spo2"] == 97

    def test_three_digit_bpm(self, device):
        parsed = device.parse_line("05-Jul-26 10:15:06  99  145  200")
        assert parsed["bpm"] == 145


class TestRegistry:
    def test_get_device_known(self):
        assert get_device("pm1000n") is DEVICE_REGISTRY["pm1000n"]
        assert get_device("pm100n") is DEVICE_REGISTRY["pm100n"]

    def test_get_device_unknown(self):
        assert get_device("nope") is None

    def test_list_devices_shape(self):
        devices = list_devices()
        assert {d["slug"] for d in devices} == {"pm100n", "pm1000n"}
        for d in devices:
            assert set(d) == {"slug", "name", "supported_connections", "default_baud_rate"}

    def test_connection_support(self):
        # PM-100N is USB-only; PM-1000N also does LAN — the /api/config
        # validation depends on these lists.
        assert get_device("pm100n").supported_connections == ["usb"]
        assert get_device("pm1000n").supported_connections == ["usb", "lan"]
