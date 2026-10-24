"""Shared isolated application fixture for workflow regression tests."""

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["CREAO_MODE"] = "mock"
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base, get_db
from app.main import app
from app import worker
from app.models import User
from app.services import token_hash
from app.config import settings


@pytest.fixture()
def system(monkeypatch):
    """Use an isolated database with real API dependencies and worker sessions."""
    monkeypatch.setattr(settings, "mock_agent_seconds", 0)
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
    yield TestClient(app), factory
    app.dependency_overrides.clear()
    engine.dispose()
