from __future__ import annotations

import time

from cryptography.fernet import Fernet

from app_state import PENDING_PAIR_TTL, PendingPair, state


def _pending(**overrides) -> PendingPair:
    kwargs = dict(
        hub_public_key="pub",
        host_ws_url="ws://192.168.1.10:8000/api/readers/ws/1",
        reader_id=1,
        caller_ip="192.168.1.10",
        requested_at=time.monotonic(),
    )
    kwargs.update(overrides)
    return PendingPair(**kwargs)


def test_pending_pair_expiry():
    p = _pending()
    assert not p.expired()
    p.requested_at -= PENDING_PAIR_TTL + 1
    assert p.expired()


def test_active_pending_pair_lazily_expires():
    state.pending_pair = _pending()
    assert state.active_pending_pair() is state.pending_pair

    state.pending_pair.requested_at -= PENDING_PAIR_TTL + 1
    assert state.active_pending_pair() is None
    assert state.pending_pair is None  # cleared, not just hidden


def test_clear_pairing_resets_everything():
    state.host_ws_url = "ws://x"
    state.encryption_key = Fernet.generate_key().decode()
    state.reader_id = 7
    state.is_paired = True
    state.pending_pair = _pending()

    state.clear_pairing()

    assert state.host_ws_url is None
    assert state.encryption_key is None
    assert state.reader_id is None
    assert state.is_paired is False
    assert state.pending_pair is None


def test_fernet_none_without_key():
    assert state.fernet() is None


def test_fernet_with_key_round_trips():
    state.encryption_key = Fernet.generate_key().decode()
    f = state.fernet()
    assert f.decrypt(f.encrypt(b"hi")) == b"hi"


def test_config_summary_shows_pending_only_while_pending():
    state.pending_pair = _pending()
    assert state.config_summary()["pending_pair"] == {"hub_ip": "192.168.1.10"}

    state.pending_pair.status = "denied"
    assert state.config_summary()["pending_pair"] is None


def test_config_summary_never_leaks_encryption_key():
    state.encryption_key = Fernet.generate_key().decode()
    summary = state.config_summary()
    assert state.encryption_key not in str(summary)
    assert "encryption_key" not in summary
