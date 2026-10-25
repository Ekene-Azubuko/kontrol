"""Return unapproved recorded-call workflows to review without erasing prior attempts."""

import json

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import now
from .models import AgentRun, Call, CoordinatorAction, DispatchAssignment, Incident, ResponsePlan, User
from .network import operation_lock
from .response_services import update_response_status
from .schemas import StrictModel

REOPENABLE_PLAN_STATUSES = {"generating", "failed", "awaiting_approval", "needs_information", "rejected", "cancelled"}


class ReopenCall(StrictModel):
    """Require the call version observed before returning to the call-type step."""

    version: int = Field(ge=1)


def reopen_call(db: Session, call_id: str, user: User, data: ReopenCall) -> Call:
    """Cancel unapproved local work and retain its reports, outputs and audit trail before reopening."""
    operation_lock(db)
    call = db.scalar(
        select(Call).where(Call.id == call_id).with_for_update().execution_options(populate_existing=True)
    )
    if call is None:
        raise HTTPException(404, "Call not found")
    if call.version != data.version or call.status != "confirmed" or not call.report_id:
        raise HTTPException(409, "Call changed or is already ready for a call type. Refresh before returning.")
    incident_ids = select(ResponsePlan.incident_id).where(ResponsePlan.report_id == call.report_id)
    plans = list(db.scalars(
        select(ResponsePlan).where(ResponsePlan.incident_id.in_(incident_ids)).with_for_update()
    ))
    # Serialize against approval and reject any incident that has already reserved resources.
    if not plans or any(
        plan.approved_at or plan.status not in REOPENABLE_PLAN_STATUSES for plan in plans
    ) or db.scalar(select(DispatchAssignment.id).where(
        DispatchAssignment.incident_id.in_([plan.incident_id for plan in plans])
    ).limit(1)):
        raise HTTPException(409, "An approved or dispatched response cannot return to call type.")
    prior_report_id = call.report_id
    for plan in plans:
        plan.status = "cancelled"
        update_response_status(db, db.get(Incident, plan.incident_id), "cancelled")
    for run in db.scalars(select(AgentRun).where(
        AgentRun.plan_id.in_([plan.id for plan in plans]), AgentRun.status.in_(["queued", "running"])
    ).with_for_update()):
        # Remote work may finish, but the worker's terminal-state check discards its late result.
        run.status, run.completed_at = "cancelled", now()
        run.error = "Dispatcher returned the recording to call type."
    call.status, call.report_id = "awaiting_review", None
    call.reviewed_transcript = None
    call.confirmed_latitude = call.confirmed_longitude = None
    call.confirmed_address = call.confirmed_by = call.confirmed_at = None
    db.add(CoordinatorAction(
        user_id=user.id,
        action="call_reopen",
        details=json.dumps({
            "call_id": call.id,
            "previous_report_id": prior_report_id,
            "previous_plan_ids": [plan.id for plan in plans],
            "reason": "Return to call type before starting a fresh workflow",
        }),
    ))
    # Existing reports preserve the prior transcript/location/category and confirmation audit.
    # Start creates new job IDs, hence new CREAO idempotency keys, only after another explicit click.
    db.flush()
    return call
