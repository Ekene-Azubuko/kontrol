"""Real row-lock coverage for competing browser answers using the same dispatcher database."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Call, LiveCallSession, User
from app.telephony_api import LiveControl, answer


def test_competing_live_answers_claim_the_call_once(postgres_system):
    """Only one tab may claim the incoming call version, even when answer requests arrive together."""
    factory = postgres_system
    with factory() as db:
        call = Call(source="live", status="live_ringing", audio_key=None, audio_content_type="audio/wav",
                    duration_seconds=0, simulation=False)
        db.add(call)
        db.flush()
        db.add(LiveCallSession(call_id=call.id, provider_sid="CA" + "a" * 32, caller="test", called="test"))
        db.commit()
        call_id, version = call.id, call.version
    barrier = Barrier(2)

    def claim():
        """Race through the actual transactional browser-answer service."""
        with factory() as db:
            user = db.scalar(select(User).where(User.role == "coordinator"))
            barrier.wait(timeout=10)
            try:
                answer(call_id, LiveControl(version=version), db, user)
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(results) == [200, 409]
