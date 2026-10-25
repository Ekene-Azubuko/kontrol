"""Real PostgreSQL row-lock and lease races for the recorded-call workflow."""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import call_worker
from app.call_services import ConfirmReview, confirm_review, LocateCall, locate_call
from app.db import now
from app.models import (
    Call,
    CoordinatorAction,
    Incident,
    Report,
    ResponsePlan,
    User,
    PublicUpdate,
    Subscription,
)
from app.response_seed import reset_response_demo
from app.transcription import TranscriptResult


def add_call(factory, status="queued"):
    """Create a remote-shaped job without relying on filesystem fixture setup."""
    with factory() as db:
        call = Call(
            status=status,
            audio_key=f"{uuid4()}.wav",
            audio_content_type="audio/wav",
            duration_seconds=10,
            sample_key="collision",
            original_transcript="SIMULATION: Two vehicles collided.",
        )
        db.add(call)
        db.commit()
        return call.id, call.version


def test_simultaneous_call_confirmations(postgres_system):
    """A second dispatcher cannot create another report or plan for the same call."""
    factory = postgres_system
    call_id, version = add_call(factory, "awaiting_review")
    barrier = Barrier(2)

    def confirm():
        """Race independent review transactions against the same observed version."""
        with factory() as db:
            user = db.scalar(select(User).where(User.role == "coordinator"))
            barrier.wait(timeout=10)
            try:
                confirm_review(
                    db,
                    call_id,
                    user,
                    ConfirmReview(
                        latitude=37.777,
                        longitude=-122.414,
                        address="Exercise intersection",
                        transcript="SIMULATION: Two people injured in collision.",
                        category="collision",
                        version=version,
                    ),
                )
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(f.result(timeout=15) for f in [pool.submit(confirm), pool.submit(confirm)]) == [
            200,
            409,
        ]
    with factory() as db:
        for model in [Report, Incident, ResponsePlan, CoordinatorAction]:
            assert len(list(db.scalars(select(model)))) == 1


def test_competing_location_lookups_release_locks_and_reject_stale_result(postgres_system, monkeypatch):
    """Both requests reach geocoding without a held lock; only one can persist against the shared version."""
    from app import call_services

    factory = postgres_system
    call_id, version = add_call(factory, "awaiting_review")
    barrier = Barrier(2)
    original = call_services.detect_location

    def resolve(text):
        """Require both external lookups to overlap, proving the reset and row locks were released."""
        barrier.wait(timeout=5)
        return original(text)

    def locate():
        """Race identical results so the test also verifies version advancement on repeated JSON."""
        with factory() as db:
            user = db.scalar(select(User).where(User.role == "coordinator"))
            try:
                locate_call(db, call_id, user, LocateCall(address="Mission exercise block", version=version))
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    monkeypatch.setattr(call_services, "detect_location", resolve)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(locate), pool.submit(locate)]
        assert sorted(future.result(timeout=10) for future in results) == [200, 409]
    with factory() as db:
        assert db.get(Call, call_id).detected_location["address"] == "Mission exercise block"
        assert len(list(db.scalars(select(CoordinatorAction)))) == 1


def test_competing_transcription_claims(postgres_system, monkeypatch):
    """Only one worker invokes transcription for a queued recording."""
    factory = postgres_system
    monkeypatch.setattr(call_worker, "SessionLocal", factory)
    add_call(factory)
    started, finish = Event(), Event()
    invoked = []

    class HeldAdapter:
        """Hold a claimed provider request until the competing worker has inspected the queue."""

        def transcribe(self, *args):
            """Record exactly one invocation outside database locks."""
            invoked.append(True)
            started.set()
            assert finish.wait(timeout=10)
            return TranscriptResult(text="SIMULATION: A reviewed recording.")

    monkeypatch.setattr(call_worker, "get_transcription_adapter", HeldAdapter)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(call_worker.process_one_call)
        assert started.wait(timeout=5)
        assert pool.submit(call_worker.process_one_call).result(timeout=5) is False
        finish.set()
        assert first.result(timeout=10)
    assert len(invoked) == 1


@pytest.mark.parametrize("action", ["retry", "reset"])
def test_late_transcription_cannot_replace_new_state(postgres_system, monkeypatch, action):
    """Late output cannot overwrite a newer retry or revive a reset exercise."""
    factory = postgres_system
    monkeypatch.setattr(call_worker, "SessionLocal", factory)
    call_id, _ = add_call(factory)
    started, finish = Event(), Event()

    class HeldAdapter:
        """Return a stale result after another transaction changes the job claim."""

        def transcribe(self, *args):
            """Pause only the first remote-shaped invocation."""
            started.set()
            assert finish.wait(timeout=10)
            return TranscriptResult(text="SIMULATION: Stale output must never be stored.")

    monkeypatch.setattr(call_worker, "get_transcription_adapter", HeldAdapter)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(call_worker.process_one_call)
        assert started.wait(timeout=5)
        with factory() as db:
            if action == "reset":
                reset_response_demo(db, db.scalar(select(User).where(User.role == "coordinator")))
            else:
                call = db.get(Call, call_id)
                call.lease_expires_at = now() - timedelta(seconds=1)
                db.flush()
                call_worker.recover_expired_calls(db)
                db.flush()
                call.status, call.claim_token = "queued", None
            db.commit()
        if action == "retry":
            from app.transcription import MockTranscription

            monkeypatch.setattr(call_worker, "get_transcription_adapter", MockTranscription)
            assert call_worker.process_one_call()
        finish.set()
        assert future.result(timeout=10)
    with factory() as db:
        call = db.get(Call, call_id)
        assert "Stale output" not in (call.original_transcript or "")
        assert call.status == ("failed" if action == "reset" else "awaiting_review")
        assert call.attempts == (3 if action == "reset" else 2)


def test_upgrade_0004_preserves_history(postgres_system):
    """Apply the additive migration to an existing schema without removing resident history."""
    factory = postgres_system
    with factory() as db:
        historical_user = db.scalar(select(User).where(User.role == "resident"))
        user_id = historical_user.id
        from app.response_seed import response_report
        from app.services import ingest_report

        report = ingest_report(db, historical_user, response_report(), simulation=False)
        incident = db.scalar(select(Incident))
        update = PublicUpdate(
            incident_id=incident.id,
            title="Historical update",
            body="Preserved historical text",
            audience="Exercise",
            author_id=user_id,
            latitude=37.777,
            longitude=-122.414,
            category="collision",
            severity="moderate",
        )
        subscription = Subscription(user_id=user_id, incident_id=incident.id)
        db.add_all([update, subscription])
        db.flush()
        report_id, update_id, subscription_id = report.id, update.id, subscription.id
        # The fixture represents an existing pre-call installation; removing only the empty new table
        # lets Alembic apply the actual additive migration to that installation.
        Call.__table__.drop(db.connection())
        db.commit()
    env = {**os.environ, "DATABASE_URL": os.environ["TEST_DATABASE_URL"]}
    subprocess.run(["alembic", "stamp", "0004"], env=env, check=True, capture_output=True)
    subprocess.run(["alembic", "upgrade", "head"], env=env, check=True, capture_output=True)
    with factory() as db:
        assert db.get(User, user_id).role == "resident"
        assert db.get(Report, report_id).description == response_report().description
        assert db.get(PublicUpdate, update_id).body == "Preserved historical text"
        assert db.get(Subscription, subscription_id).user_id == user_id
        assert list(db.scalars(select(Call))) == []
        from sqlalchemy import text

        db.execute(text("DROP TABLE alembic_version"))
        db.commit()
