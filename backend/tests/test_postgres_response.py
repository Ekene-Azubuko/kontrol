"""Optional real PostgreSQL concurrency checks in an explicitly disposable test database."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app import worker
from app.config import settings
from app.creao import MockAdapter
from app.db import Base
from app.models import (
    AgentRun,
    DispatchAssignment,
    EmergencyVehicle,
    Hospital,
    Incident,
    Report,
    ResponsePlan,
    User,
)
from app.response_schemas import PlanDecision
from app.response_seed import reset_response_demo, response_report, seed_network
from app.response_services import decide_plan
from app.services import ingest_report, token_hash


@pytest.fixture()
def postgres_system(monkeypatch):
    """Allow real row locks only against the named throwaway database, never the demo database."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL concurrency checks")
    if make_url(url).database != "kontrol_response_test":
        raise RuntimeError("Concurrency tests require the disposable kontrol_response_test database")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
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


def submit(factory):
    """Create an ordinary source report and its intake job in one transaction."""
    with factory() as db:
        resident = db.scalar(select(User).where(User.role == "resident"))
        report = ingest_report(db, resident, response_report())
        db.commit()
        return report.id


def test_parallel_evaluations_join_once(postgres_system, monkeypatch):
    """Both evaluation calls must start concurrently, then produce exactly one planning job."""
    factory = postgres_system
    submit(factory)
    worker.process_one()
    barrier = Barrier(2)

    class ParallelAdapter(MockAdapter):
        """Hold each evaluation until its sibling is also executing outside database locks."""

        def invoke(self, stage, payload):
            barrier.wait(timeout=10)
            return super().invoke(stage, payload)

    monkeypatch.setattr(worker, "get_adapter", ParallelAdapter)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker.process_one) for _ in range(2)]
        assert all(future.result(timeout=15) for future in futures)
    with factory() as db:
        runs = list(db.scalars(select(AgentRun)))
        assert {r.stage for r in runs if r.status == "completed"} == {"intake", "hospital", "dispatch"}
        assert len([r for r in runs if r.stage == "planning"]) == 1


def test_simultaneous_approvals_cannot_double_book(postgres_system):
    """Real row locks allow only one competing proposal to acquire the same vehicle and beds."""
    factory = postgres_system
    for _ in range(2):
        submit(factory)
        for _ in range(4):
            worker.process_one()
    with factory() as db:
        plans = [(p.id, p.version) for p in db.scalars(select(ResponsePlan))]
    barrier = Barrier(2)

    def approve(plan):
        """Race independent coordinator transactions against an identical resource selection."""
        with factory() as db:
            user = db.scalar(select(User).where(User.role == "coordinator"))
            barrier.wait(timeout=10)
            try:
                decide_plan(
                    db,
                    plan[0],
                    user,
                    PlanDecision(action="approve", version=plan[1], note="Reviewed concurrent test proposal"),
                )
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(approve, plans)) == [200, 409]
    with factory() as db:
        assignments = list(db.scalars(select(DispatchAssignment)))
        assert len(assignments) == 2 and len({a.vehicle_id for a in assignments}) == 2
        assert sum(h.reserved_beds for h in db.scalars(select(Hospital))) == 2


def test_reset_discards_in_flight_agent_output(postgres_system, monkeypatch):
    """An agent returning after reset cannot recreate plans, jobs, findings or resource changes."""
    factory = postgres_system
    submit(factory)
    started, finish = Event(), Event()

    class HeldAdapter(MockAdapter):
        """Pause a remote-shaped call while the coordinator resets the exercise."""

        def invoke(self, stage, payload):
            started.set()
            assert finish.wait(timeout=10)
            return super().invoke(stage, payload)

    monkeypatch.setattr(worker, "get_adapter", HeldAdapter)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker.process_one)
        assert started.wait(timeout=5)
        with factory() as db:
            reset_response_demo(db, db.scalar(select(User).where(User.role == "coordinator")))
            db.commit()
        finish.set()
        assert future.result(timeout=10)
    with factory() as db:
        assert all(r.status == "cancelled" for r in db.scalars(select(AgentRun)))
        assert db.scalar(select(ResponsePlan)).status == "cancelled"
        assert db.scalar(select(Incident)).response_status == "cancelled"
        assert db.scalar(select(Report)).status == "cancelled"
        assert all(v.status == "available" for v in db.scalars(select(EmergencyVehicle)))
