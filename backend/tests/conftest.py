"""Shared isolated application fixture for workflow regression tests."""

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["CREAO_MODE"] = "mock"
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base, get_db
from app.main import app
from app import worker, call_worker
from app.models import User
from app.services import token_hash
from app.config import settings


@pytest.fixture()
def system(monkeypatch, tmp_path):
    """Use an isolated database with real API dependencies and worker sessions."""
    monkeypatch.setattr(settings, "mock_agent_seconds", 0)
    monkeypatch.setattr(settings, "live_simulation_enabled", False)
    monkeypatch.setattr(settings, "transcription_mode", "mock")
    monkeypatch.setattr(settings, "call_audio_dir", str(tmp_path / "audio"))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add_all(
            [
                User(name="Demo resident", role="resident", token_hash=token_hash("demo-resident")),
                User(name="Demo coordinator", role="coordinator", token_hash=token_hash("demo-coordinator")),
                User(name="Other resident", role="resident", token_hash=token_hash("other-resident")),
            ]
        )
        from app.response_seed import seed_network

        seed_network(db)
        db.commit()

    def dependency():
        """Replace only the request session; retain real authentication behavior."""
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(call_worker, "SessionLocal", factory)
    yield TestClient(app), factory
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture()
def postgres_system(monkeypatch):
    """Allow real row locks only against the named throwaway database, never the demo database."""
    from app.response_seed import seed_network

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL concurrency checks")
    if make_url(url).database != "kontrol_response_test":
        raise RuntimeError("Concurrency tests require the disposable kontrol_response_test database")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(call_worker, "SessionLocal", factory)
    monkeypatch.setattr(settings, "mock_agent_seconds", 0)
    with factory() as db:
        db.add_all(
            [
                User(name="Test resident", role="resident", token_hash=token_hash("test-resident")),
                User(name="Test coordinator", role="coordinator", token_hash=token_hash("test-coordinator")),
            ]
        )
        seed_network(db)
        db.commit()
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()
