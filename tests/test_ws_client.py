from __future__ import annotations

import json

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app_state import state
from pairing import derive_fernet_key, public_key_b64
from transport.ws_client import _send_encrypted


class FakeWS:
    def __init__(self):
        self.sent: list[bytes] = []

    async def send(self, data):
        self.sent.append(data)


async def test_send_encrypted_round_trip():
    state.encryption_key = Fernet.generate_key().decode()
    ws = FakeWS()
    payload = {"type": "sensor", "values": {"spo2": 98, "bpm": 72, "perfusion": 90}}

    await _send_encrypted(ws, payload)

    assert len(ws.sent) == 1
    decrypted = json.loads(Fernet(state.encryption_key.encode()).decrypt(ws.sent[0]))
    assert decrypted == payload


async def test_send_encrypted_skips_without_key():
    ws = FakeWS()
    await _send_encrypted(ws, {"type": "ping"})
    assert ws.sent == []  # never send plaintext


async def test_hub_can_decrypt_with_pairing_derived_key():
    # End-to-end: key from the pairing exchange must decrypt what the
    # reader's WS sender encrypts.
    hub_priv = X25519PrivateKey.generate()
    reader_priv = X25519PrivateKey.generate()
    state.encryption_key = derive_fernet_key(reader_priv, public_key_b64(hub_priv))

    ws = FakeWS()
    await _send_encrypted(ws, {"type": "handshake", "device_name": "shh-reader"})

    hub_key = derive_fernet_key(hub_priv, public_key_b64(reader_priv))
    msg = json.loads(Fernet(hub_key.encode()).decrypt(ws.sent[0]))
    assert msg["type"] == "handshake"
