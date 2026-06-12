"""X25519 key agreement for hub pairing.

Both sides exchange ephemeral public keys and derive the same Fernet key
via ECDH + HKDF, so the symmetric key itself never crosses the network.
This defeats passive sniffing of the pairing exchange; an active MITM on
the LAN could still substitute public keys — full protection needs TLS
(out of scope). The mitigation is the Allow prompt on the reader showing
the requesting hub's IP.

The constants here must match the hub's pairing helper exactly.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

PAIR_PROTOCOL_VERSION = 2
PAIR_HKDF_INFO = b"shh-reader-pairing-v2"


def public_key_b64(priv: X25519PrivateKey) -> str:
    return base64.urlsafe_b64encode(
        priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()


def derive_fernet_key(priv: X25519PrivateKey, peer_pub_b64: str) -> str:
    peer = X25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(peer_pub_b64))
    shared = priv.exchange(peer)
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=PAIR_HKDF_INFO
    ).derive(shared)
    return base64.urlsafe_b64encode(key).decode()  # valid Fernet key
