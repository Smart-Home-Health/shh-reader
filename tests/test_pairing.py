from __future__ import annotations

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from pairing import (
    PAIR_HKDF_INFO,
    PAIR_PROTOCOL_VERSION,
    derive_fernet_key,
    public_key_b64,
)


def test_constants_match_hub_contract():
    # These MUST stay in sync with the hub's utils/pairing_crypto.py.
    # If this test fails, pairing against released hubs breaks.
    assert PAIR_PROTOCOL_VERSION == 2
    assert PAIR_HKDF_INFO == b"shh-reader-pairing-v2"


def test_public_key_is_urlsafe_b64_raw32():
    pub = public_key_b64(X25519PrivateKey.generate())
    raw = base64.urlsafe_b64decode(pub)
    assert len(raw) == 32


def test_both_sides_derive_same_key():
    # Simulate the full exchange: hub and reader each generate an ephemeral
    # keypair, swap public keys, and must land on the identical Fernet key.
    hub_priv = X25519PrivateKey.generate()
    reader_priv = X25519PrivateKey.generate()

    hub_key = derive_fernet_key(hub_priv, public_key_b64(reader_priv))
    reader_key = derive_fernet_key(reader_priv, public_key_b64(hub_priv))

    assert hub_key == reader_key


def test_derived_key_is_valid_fernet():
    a, b = X25519PrivateKey.generate(), X25519PrivateKey.generate()
    key = derive_fernet_key(a, public_key_b64(b))
    f = Fernet(key.encode())  # raises if not a valid 32-byte urlsafe-b64 key
    assert f.decrypt(f.encrypt(b"vitals")) == b"vitals"


def test_different_exchanges_yield_different_keys():
    a, b, c = (X25519PrivateKey.generate() for _ in range(3))
    assert derive_fernet_key(a, public_key_b64(b)) != derive_fernet_key(a, public_key_b64(c))
