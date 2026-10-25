"""Race deletion against call confirmation using PostgreSQL's real transaction locks."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import select

from app.call_delete import DeleteCall, mark_call_deleted
from app.call_services import ConfirmReview, confirm_review
from app.models import Call, CoordinatorAction, Report, User
from test_postgres_calls import add_call


def test_delete_and_confirm_cannot_both_win(postgres_system):
    """The observed call version can be confirmed or deleted, never both concurrently."""
    factory = postgres_system
    call_id, version = add_call(factory, 'awaiting_review')
    barrier = Barrier(2)

    def act(kind):
        """Compete for the same call with independently committed database sessions."""
        with factory() as db:
            user = db.scalar(select(User).where(User.role == 'coordinator'))
            barrier.wait(timeout=10)
            try:
                if kind == 'delete':
                    mark_call_deleted(db, call_id, user, DeleteCall(version=version))
                else:
                    confirm_review(db, call_id, user, ConfirmReview(
                        latitude=37.777, longitude=-122.414, address='Exercise location',
                        transcript='SIMULATION: Two vehicles collided with injuries unknown.',
                        category='collision', version=version,
                    ))
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(act, kind) for kind in ['delete', 'confirm']]
        assert sorted(f.result(timeout=15) for f in futures) == [200, 409]
    with factory() as db:
        call = db.get(Call, call_id)
        assert bool(db.scalar(select(Report.id))) == (call.status == 'confirmed')
        assert len(list(db.scalars(select(CoordinatorAction)))) == 1


def test_simultaneous_deletes_are_audited_once(postgres_system):
    """Two dispatchers deleting the same recording cannot emit duplicate deletion events."""
    factory = postgres_system
    call_id, version = add_call(factory, 'awaiting_review')
    barrier = Barrier(2)

    def remove():
        """Delete through the same serialized service used by the API."""
        with factory() as db:
            user = db.scalar(select(User).where(User.role == 'coordinator'))
            barrier.wait(timeout=10)
            try:
                mark_call_deleted(db, call_id, user, DeleteCall(version=version))
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(remove), pool.submit(remove)]
        assert sorted(f.result(timeout=15) for f in futures) == [200, 404]
    with factory() as db:
        assert db.get(Call, call_id).status == 'deleted'
        assert len(list(db.scalars(select(CoordinatorAction)))) == 1
