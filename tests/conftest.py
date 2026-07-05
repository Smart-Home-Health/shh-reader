from __future__ import annotations

import dataclasses

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import db
from app_state import AppState, state


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    """Reset the module-level state singleton and sandbox the settings DB.

    Modules hold a reference to the singleton (`from app_state import state`),
    so it can't be swapped out — instead every field is reset in place from a
    fresh AppState. DB_PATH is pointed at a per-test temp file so tests never
    touch data/shh_reader.db.
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_settings.db")
    fresh = AppState()
    for f in dataclasses.fields(AppState):
        setattr(state, f.name, getattr(fresh, f.name))
    yield state


@pytest.fixture
def client():
    """TestClient on a lifespan-free app: same routers, no auto-start."""
    from routes.api import router as api_router
    from routes.pages import router as pages_router

    app = FastAPI()
    app.include_router(api_router)
    app.include_router(pages_router)
    return TestClient(app)
