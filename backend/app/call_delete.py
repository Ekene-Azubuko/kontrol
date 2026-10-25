"""Delete private recordings without erasing their existing response history."""

import json
import logging

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .call_audio import audio_path
from .models import Call, CoordinatorAction, User
from .network import operation_lock
from .schemas import StrictModel


class DeleteCall(StrictModel):
    """Require the version seen when the dispatcher confirmed deletion."""

    version: int = Field(ge=1)


def mark_call_deleted(db: Session, call_id: str, user: User, data: DeleteCall) -> None:
    """Hide the call and invalidate transcription before touching its audio file."""
    operation_lock(db)
    call = db.scalar(select(Call).where(Call.id == call_id).with_for_update()
                     .execution_options(populate_existing=True))
    if call is None or call.status == "deleted":
        raise HTTPException(404, "Recording not found")
    if call.version != data.version:
        raise HTTPException(409, "Recording changed. Refresh and confirm deletion again.")
    call.status, call.claim_token, call.lease_expires_at = "deleted", None, None
    db.add(CoordinatorAction(
        user_id=user.id,
        action="call_delete",
        details=json.dumps({"call_id": call.id, "report_id": call.report_id,
                            "reason": "Dispatcher deleted recording; response history retained"}),
    ))
    db.flush()


def cleanup_deleted_calls(db: Session, call_id: str | None = None) -> bool:
    """Retry file removal from durable tombstones, then remove their private call rows."""
    operation_lock(db)
    query = select(Call).where(Call.status == "deleted")
    if call_id is not None:
        query = query.where(Call.id == call_id)
    pending = False
    for call in db.scalars(query.limit(20).with_for_update()):
        try:
            audio_path(call.audio_key).unlink(missing_ok=True)
        except OSError:
            # Leave a hidden tombstone so a worker can retry after a storage failure or restart.
            logging.warning("Recording cleanup pending for call %s", call.id)
            pending = True
            continue
        db.delete(call)
    db.flush()
    return pending
