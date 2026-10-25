"""Exercise recording reruns against simultaneous review and approval transactions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import select

from app import worker
from app.call_reopen import ReopenCall, reopen_call
from app.call_services import ConfirmReview, confirm_review
from app.models import Call, DispatchAssignment, ResponsePlan, User
from app.response_schemas import PlanDecision
from app.response_services import decide_plan
from test_postgres_calls import add_call


def confirmed_call(factory):
    """Create a confirmed fictional call with a real queued workflow in the disposable database."""
    call_id, version = add_call(factory, "awaiting_review")
    with factory() as db:
        user = db.scalar(select(User).where(User.role == "coordinator"))
        call = confirm_review(db, call_id, user, ConfirmReview(
            latitude=37.777, longitude=-122.414, address="Exercise intersection",
            transcript="SIMULATION: Two vehicles collided; 2 people reported injured.",
            category="collision", version=version,
        ))
        plan = db.scalar(select(ResponsePlan).where(ResponsePlan.report_id == call.report_id))
        db.commit()
        return call.id, call.version, plan.id


def test_simultaneous_reopen_requests(postgres_system):
    """Only one dispatcher can return the same call version to review."""
    factory = postgres_system
    call_id, version, plan_id = confirmed_call(factory)
    barrier = Barrier(2)

    def reopen():
        """Race independently scoped transactions through the normal row-lock boundary."""
        with factory() as db:
            user = db.scalar(select(User).where(User.role == "coordinator"))
            barrier.wait(timeout=10)
            try:
                reopen_call(db, call_id, user, ReopenCall(version=version))
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reopen), pool.submit(reopen)]
        assert sorted(f.result(timeout=15) for f in futures) == [200, 409]
    with factory() as db:
        assert db.get(Call, call_id).status == "awaiting_review"
        assert db.get(ResponsePlan, plan_id).status == "cancelled"


def test_reopen_and_approval_cannot_both_win(postgres_system):
    """Cancellation never races past an approval that has reserved vehicles or beds."""
    factory = postgres_system
    call_id, call_version, plan_id = confirmed_call(factory)
    for _ in range(4):
        assert worker.process_one()
    with factory() as db:
        plan_version = db.get(ResponsePlan, plan_id).version
    barrier = Barrier(2)

    def act(action):
        """Race the real approval service against reopening using their common operation lock."""
        with factory() as db:
            user = db.scalar(select(User).where(User.role == "coordinator"))
            barrier.wait(timeout=10)
            try:
                if action == "reopen":
                    reopen_call(db, call_id, user, ReopenCall(version=call_version))
                else:
                    decide_plan(db, plan_id, user, PlanDecision(
                        action="approve", version=plan_version, note="Reviewed simulation",
                    ))
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(act, action) for action in ("reopen", "approve")]
        assert sorted(f.result(timeout=15) for f in futures) == [200, 409]
    with factory() as db:
        dispatched = bool(db.scalar(select(DispatchAssignment.id)))
        assert (db.get(Call, call_id).status == "confirmed") == dispatched
        assert (db.get(ResponsePlan, plan_id).status == "cancelled") != dispatched
