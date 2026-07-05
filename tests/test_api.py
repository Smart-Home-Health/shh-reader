from __future__ import annotations

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app_state import PENDING_PAIR_TTL, state
from db import load_settings
from pairing import PAIR_PROTOCOL_VERSION, derive_fernet_key, public_key_b64
from routes.api import _extract_reader_id, _fix_ws_url

HUB_WS = "ws://192.168.1.5:8000/api/readers/ws/4"


def _pair(client, hub_pub: str = "x" * 43, host_url: str = HUB_WS):
    return client.post("/api/pair", json={
        "host_url": host_url,
        "hub_public_key": hub_pub,
        "protocol_version": PAIR_PROTOCOL_VERSION,
    })


# ---------------------------------------------------------------- helpers

class TestUrlHelpers:
    def test_extract_reader_id(self):
        assert _extract_reader_id("ws://h:8000/api/readers/ws/5") == 5
        assert _extract_reader_id("ws://h:8000/api/readers/ws/5/") == 5
        assert _extract_reader_id("ws://h:8000/api/readers/ws/abc") is None

    def test_fix_ws_url_rewrites_docker_hosts(self):
        for bad in ("host.docker.internal", "localhost", "127.0.0.1"):
            fixed = _fix_ws_url(f"ws://{bad}:8000/api/readers/ws/2", "192.168.1.5")
            assert fixed == "ws://192.168.1.5:8000/api/readers/ws/2"

    def test_fix_ws_url_keeps_real_hosts(self):
        assert _fix_ws_url(HUB_WS, "10.0.0.9") == HUB_WS

    def test_fix_ws_url_without_port(self):
        assert _fix_ws_url("ws://localhost/ws/1", "10.0.0.9") == "ws://10.0.0.9/ws/1"


# ---------------------------------------------------------------- config

class TestConfig:
    def test_get_config_defaults(self, client):
        cfg = client.get("/api/config").json()
        assert cfg["device_type"] is None
        assert cfg["is_paired"] is False
        assert cfg["is_running"] is False
        assert cfg["pending_pair"] is None

    def test_devices_listed(self, client):
        slugs = {d["slug"] for d in client.get("/api/devices").json()}
        assert slugs == {"pm100n", "pm1000n"}

    def test_set_config_unknown_device(self, client):
        r = client.post("/api/config", json={"device_type": "nope", "connection_mode": "usb"})
        assert r.status_code == 400

    def test_set_config_unsupported_connection(self, client):
        # PM-100N is USB-only
        r = client.post("/api/config", json={"device_type": "pm100n", "connection_mode": "lan"})
        assert r.status_code == 400

    def test_set_config_lan_persists(self, client):
        r = client.post("/api/config", json={
            "device_type": "pm1000n", "connection_mode": "lan", "lan_listen_port": 6001,
        })
        assert r.status_code == 200
        assert state.device_type == "pm1000n"
        assert state.lan_listen_port == 6001
        # settings must survive a restart
        saved = load_settings()
        assert saved["device_type"] == "pm1000n"
        assert saved["lan_listen_port"] == 6001

    def test_set_config_usb_default_baud(self, client):
        r = client.post("/api/config", json={
            "device_type": "pm100n", "connection_mode": "usb", "usb_port": "/dev/ttyUSB0",
        })
        assert r.status_code == 200
        assert state.baud_rate == 115200  # device default when none given

    def test_start_requires_config(self, client):
        assert client.post("/api/start").status_code == 400

    def test_start_rejects_double_start(self, client):
        state.is_running = True
        assert client.post("/api/start").status_code == 400


# ---------------------------------------------------------------- pairing

class TestPairingFlow:
    def test_old_protocol_rejected(self, client):
        r = client.post("/api/pair", json={
            "host_url": HUB_WS, "hub_public_key": "x", "protocol_version": 1,
        })
        assert r.status_code == 400
        assert state.pending_pair is None  # nothing recorded

    def test_pair_creates_pending(self, client):
        r = _pair(client)
        assert r.json()["status"] == "pending"
        assert state.pending_pair is not None
        assert state.pending_pair.reader_id == 4
        assert state.is_paired is False  # nothing persisted until Allow
        assert client.get("/api/pair/status").json() == {"status": "pending"}

    def test_pair_rewrites_docker_internal_url(self, client):
        # TestClient's caller IP is "testclient" — good enough to prove the rewrite
        _pair(client, host_url="ws://host.docker.internal:8000/api/readers/ws/4")
        assert state.pending_pair.host_ws_url == "ws://testclient:8000/api/readers/ws/4"

    def test_newer_request_replaces_older(self, client):
        _pair(client, hub_pub="first")
        _pair(client, hub_pub="second")
        assert state.pending_pair.hub_public_key == "second"

    def test_status_none_without_request(self, client):
        assert client.get("/api/pair/status").json() == {"status": "none"}

    def test_pending_request_expires(self, client):
        _pair(client)
        state.pending_pair.requested_at -= PENDING_PAIR_TTL + 1
        assert client.get("/api/pair/status").json() == {"status": "none"}

    def test_respond_without_pending(self, client):
        r = client.post("/api/pair/respond", json={"accept": True})
        assert r.status_code == 400

    def test_deny_reports_once_then_clears(self, client):
        _pair(client)
        r = client.post("/api/pair/respond", json={"accept": False})
        assert r.json() == {"ok": True, "is_paired": False}
        assert state.is_paired is False
        assert state.encryption_key is None
        # the hub's poll sees the denial exactly once
        assert client.get("/api/pair/status").json() == {"status": "denied"}
        assert client.get("/api/pair/status").json() == {"status": "none"}

    def test_accept_derives_shared_key_with_hub(self, client):
        # Full exchange from the hub's perspective: after Allow, the key the
        # hub derives from the reader's public key must equal the reader's.
        hub_priv = X25519PrivateKey.generate()
        _pair(client, hub_pub=public_key_b64(hub_priv))

        r = client.post("/api/pair/respond", json={"accept": True})
        assert r.json() == {"ok": True, "is_paired": True}
        assert state.is_paired is True
        assert state.host_ws_url == HUB_WS
        assert state.reader_id == 4

        status = client.get("/api/pair/status").json()
        assert status["status"] == "approved"
        hub_key = derive_fernet_key(hub_priv, status["reader_public_key"])
        assert hub_key == state.encryption_key

        # and the shared key actually encrypts/decrypts across sides
        token = Fernet(hub_key.encode()).encrypt(b"sensor")
        assert state.fernet().decrypt(token) == b"sensor"

        # pairing must survive a restart
        saved = load_settings()
        assert saved["is_paired"] is True
        assert saved["encryption_key"] == state.encryption_key

    def test_approved_status_is_idempotent_until_ttl(self, client):
        _pair(client, hub_pub=public_key_b64(X25519PrivateKey.generate()))
        client.post("/api/pair/respond", json={"accept": True})
        first = client.get("/api/pair/status").json()
        second = client.get("/api/pair/status").json()
        assert first == second  # hub's poll can safely retry

    def test_repair_keeps_existing_pairing_until_allow(self, client):
        # Paired reader gets a new pairing request: existing pairing intact
        # while pending, and a Deny leaves it untouched.
        _pair(client, hub_pub=public_key_b64(X25519PrivateKey.generate()))
        client.post("/api/pair/respond", json={"accept": True})
        old_key = state.encryption_key

        _pair(client, hub_pub=public_key_b64(X25519PrivateKey.generate()))
        assert state.is_paired is True
        assert state.encryption_key == old_key

        client.post("/api/pair/respond", json={"accept": False})
        assert state.is_paired is True
        assert state.encryption_key == old_key

    def test_unpair_clears_and_persists(self, client):
        _pair(client, hub_pub=public_key_b64(X25519PrivateKey.generate()))
        client.post("/api/pair/respond", json={"accept": True})

        r = client.post("/api/unpair")
        assert r.json() == {"ok": True}
        assert state.is_paired is False
        assert state.encryption_key is None
        assert load_settings()["is_paired"] is False


# ---------------------------------------------------------------- data gating

class TestLatest:
    VALUES = {"spo2": 97, "spo2_alarm": False, "bpm": 64, "bpm_alarm": False, "perfusion": 90}
    SENTINEL = {"spo2": -1, "spo2_alarm": False, "bpm": -1, "bpm_alarm": False, "perfusion": -1}

    def test_unpaired_without_token_gets_sentinel(self, client):
        state.latest_values = self.VALUES
        assert client.get("/api/latest").json() == self.SENTINEL

    def test_unpaired_with_bad_token_gets_sentinel(self, client):
        state.latest_values = self.VALUES
        r = client.get("/api/latest", headers={"x-ui-token": "wrong"})
        assert r.json() == self.SENTINEL

    def test_unpaired_with_ui_token_gets_values(self, client):
        state.latest_values = self.VALUES
        r = client.get("/api/latest", headers={"x-ui-token": state.ui_token})
        assert r.json() == self.VALUES

    def test_paired_gets_values(self, client):
        state.is_paired = True
        state.latest_values = self.VALUES
        assert client.get("/api/latest").json() == self.VALUES


# ---------------------------------------------------------------- misc

class TestMisc:
    def test_status_shape(self, client):
        s = client.get("/api/status").json()
        assert s["is_running"] is False
        assert s["is_paired"] is False
        assert s["ws_state"] == "disconnected"
        assert s["data_queue_size"] == 0

    def test_mqtt_config_persists(self, client):
        r = client.post("/api/mqtt", json={
            "mqtt_enabled": True, "mqtt_broker": "192.168.1.9",
            "mqtt_topic1": "shh/spo2",
        })
        assert r.status_code == 200
        assert state.mqtt_enabled is True
        saved = load_settings()
        assert saved["mqtt_enabled"] is True
        assert saved["mqtt_broker"] == "192.168.1.9"
        assert saved["mqtt_topic1"] == "shh/spo2"

    def test_diagnostics_returns_raw_buffer(self, client):
        state.raw_buffer.append("raw line 1")
        state.raw_buffer.append("raw line 2")
        assert client.get("/api/diagnostics").json() == {"lines": ["raw line 1", "raw line 2"]}

    def test_index_page_carries_ui_token(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert state.ui_token in r.text
