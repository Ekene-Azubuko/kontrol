"""Role-scoped HTTP API for the Kontrol operations workspace."""

import asyncio
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.orm.exc import StaleDataError

from .config import settings
from .call_api import router as call_router
from .response_api import router as response_router
from .dependencies import DB, Principal, Coordinator, current_user
from .network import operation_lock, record
from .db import SessionLocal, now
from .models import (
    AgentFinding,
    AgentRun,
    CoordinatorAction,
    Evidence,
    Incident,
    IncidentReport,
    Report,
    Resource,
    ResourceRequest,
    ResponsePlan,
    Simulation,
)
from .schemas import (
    IncidentAction,
    RequestInput,
    ResourceInput,
    SimulationInput,
)
from .services import (
    apply_incident_action,
    approve_resource,
    require_record,
)

app = FastAPI(
    title="Kontrol | Emergency Intelligence",
    description="SIMULATION (NOT FOR EMERGENCY USE). Recorded-call dispatcher co-pilot.",
    version="1.0.0",
)


@app.exception_handler(StaleDataError)
async def stale_write(request: Request, exc: StaleDataError):
    """Surface concurrent changes as reviewable conflicts instead of lost updates."""
    return JSONResponse(status_code=409, content={"detail": "Record changed; refresh before retrying"})


@app.get("/health")
def health(db: DB):
    """Probe database connectivity for container readiness."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "agent_mode": settings.creao_mode}


@app.get("/session")
def session(user: Principal):
    """Expose the current principal without its stored credential digest."""
    return record(user, {"token_hash"})


@app.get("/config")
def configuration():
    """Advertise demo availability without exposing secrets."""
    return {"account_management": False, "agent_mode": settings.creao_mode}


@app.get("/reports")
def reports(db: DB, user: Coordinator):
    """Keep private source history visible to dispatchers independently of provider mode."""
    query = select(Report).order_by(Report.created_at.desc())
    result = []
    for row in db.scalars(query.limit(200)):
        item = record(row, {"photo"})
        item["incident_id"] = db.scalar(
            select(IncidentReport.incident_id).where(IncidentReport.report_id == row.id)
        )
        result.append(item)
    return result


@app.get("/reports/{report_id}")
def report_detail(report_id: str, db: DB, user: Coordinator):
    """Return historical source text only after dispatcher authorization."""
    report = require_record(db, Report, report_id)
    return record(report)


@app.get("/incidents")
def incidents(db: DB, user: Coordinator):
    """Return internal incident state exclusively to coordinators."""
    return [
        record(row)
        for row in db.scalars(
            select(Incident)
            .order_by(Incident.created_at.desc())
        )
    ]


@app.get("/incidents/{incident_id}")
def incident_detail(incident_id: str, db: DB, user: Coordinator):
    """Assemble the review dossier with original observations and execution evidence."""
    incident = require_record(db, Incident, incident_id)
    report_ids = select(IncidentReport.report_id).where(IncidentReport.incident_id == incident_id)
    return {
        **record(incident),
        "reports": [record(r) for r in db.scalars(select(Report).where(Report.id.in_(report_ids)))],
        "evidence": [
            record(r) for r in db.scalars(select(Evidence).where(Evidence.incident_id == incident_id))
        ],
        "findings": [
            record(r) for r in db.scalars(select(AgentFinding).where(AgentFinding.incident_id == incident_id))
        ],
        "history": [
            record(r)
            for r in db.scalars(
                select(CoordinatorAction)
                .where(CoordinatorAction.incident_id == incident_id)
                .order_by(CoordinatorAction.created_at.desc())
            )
        ],
    }


@app.post("/incidents/{incident_id}/actions")
def incident_action(incident_id: str, data: IncidentAction, db: DB, user: Coordinator):
    """Record a version-checked human review decision."""
    incident = require_record(db, Incident, incident_id)
    apply_incident_action(db, incident, user, data)
    db.commit()
    return record(incident)


@app.get("/resources")
def resources(db: DB, user: Coordinator):
    """Keep the legacy seeded resource directory out of live product surfaces."""
    if settings.creao_mode == "live" and not settings.live_simulation_enabled:
        return []
    query = select(Resource).order_by(Resource.name)
    if user.role != "coordinator":
        query = query.where(Resource.published.is_(True))
    return [record(row) for row in db.scalars(query)]


@app.patch("/resources/{resource_id}")
def edit_resource(resource_id: str, data: ResourceInput, db: DB, user: Coordinator):
    """Update confirmed capacity with optimistic concurrency protection."""
    resource = require_record(db, Resource, resource_id)
    if data.occupancy > data.capacity:
        raise HTTPException(422, "Occupancy cannot exceed capacity")
    if data.version != resource.version:
        raise HTTPException(409, "Resource changed; refresh before editing")
    resource.capacity, resource.occupancy, resource.published = data.capacity, data.occupancy, data.published
    resource.confirmed_at = now()
    db.add(CoordinatorAction(user_id=user.id, action="resource_edit", details=f"Confirmed {resource.name}"))
    db.commit()
    return record(resource)


@app.get("/resource-requests")
def resource_requests(db: DB, user: Coordinator):
    """Keep proposals against legacy seeded resources out of live product surfaces."""
    if settings.creao_mode == "live" and not settings.live_simulation_enabled:
        return []
    return [
        record(row)
        for row in db.scalars(select(ResourceRequest).order_by(ResourceRequest.created_at.desc()))
    ]


@app.post("/resource-requests")
def request_resource(data: RequestInput, db: DB, user: Coordinator):
    """Create a pending proposal without changing resource occupancy."""
    require_record(db, Incident, data.incident_id)
    require_record(db, Resource, data.resource_id)
    proposal = ResourceRequest(**data.model_dump())
    db.add(proposal)
    db.commit()
    return record(proposal)


@app.post("/resource-requests/{request_id}/approve")
def approve_request(request_id: str, db: DB, user: Coordinator):
    """Approve simulated allocation once, within the resource capacity transaction."""
    proposal = db.scalar(select(ResourceRequest).where(ResourceRequest.id == request_id).with_for_update())
    if not proposal:
        raise HTTPException(404, "Request not found")
    approve_resource(db, proposal, user)
    db.commit()
    return record(proposal)


@app.get("/agents")
def agents(db: DB, user: Coordinator):
    """Return actual persisted executions rather than fabricated activity."""
    query = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(300)
    return [record(r) for r in db.scalars(query)]


@app.post("/agents/{run_id}/retry")
def retry_agent(run_id: str, db: DB, user: Coordinator):
    """Bound coordinator-requested retries and retain the prior failure description."""
    require_record(db, AgentRun, run_id)
    operation_lock(db)
    run = db.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
    from .call_services import require_exercise_execution

    if run and db.get(Report, run.report_id).simulation:
        require_exercise_execution()
    if not run or run.status != "failed" or run.attempts >= 3:
        raise HTTPException(409, "Only failed runs with fewer than three attempts can retry")
    if not run.plan_id:
        raise HTTPException(409, "Legacy agent jobs cannot be retried")
    if run.stage == "planning":
        upstream = list(db.scalars(select(AgentRun).where(
            AgentRun.plan_id == run.plan_id,
            AgentRun.stage.in_(["hospital", "dispatch"]),
        )))
        if len(upstream) != 2 or any(r.status != "completed" or not r.output for r in upstream):
            raise HTTPException(409, "Hospital and Dispatch must complete successfully before planning")
    plan = db.get(ResponsePlan, run.plan_id)
    if plan.status not in {"failed", "generating"}:
        raise HTTPException(409, "This workflow is no longer eligible for retry")
    plan.status = "generating"
    run.status = "queued"
    db.add(
        CoordinatorAction(
            user_id=user.id, incident_id=run.incident_id, action="agent_retry", details=f"Retry {run.id}"
        )
    )
    db.commit()
    return record(run)


@app.get("/activity")
def activity(db: DB, user: Coordinator):
    """Expose the human decision history to the operations dashboard."""
    query = select(CoordinatorAction).order_by(CoordinatorAction.created_at.desc()).limit(50)
    return [record(row) for row in db.scalars(query)]


@app.get("/simulation")
def simulation(db: DB, user: Coordinator):
    """Expose durable replay and worker health state."""
    state = db.scalar(select(Simulation))
    return (
        {**record(state), "mode": settings.creao_mode}
        if state
        else {"running": False, "cursor": 0, "speed": 1, "mode": settings.creao_mode}
    )


@app.post("/simulation")
def control_simulation(data: SimulationInput, db: DB, user: Coordinator):
    """Control non-destructive replay; reset rewinds the cursor and preserves audit records."""
    if settings.app_env == "production":
        raise HTTPException(403, "Simulation controls are disabled in production")
    state = db.scalar(select(Simulation).with_for_update())
    if not state:
        raise HTTPException(409, "Demo scenario is not seeded")
    if data.action == "start":
        if settings.creao_mode == "live" and not settings.live_simulation_enabled:
            raise HTTPException(409, "Live simulation is disabled to prevent unexpected paid requests")
        state.running = True
    elif data.action == "pause":
        state.running = False
    elif data.action == "reset":
        state.running, state.cursor = False, 0
    else:
        state.speed = data.speed
    db.commit()
    return record(state)


@app.get("/events")
async def events(request: Request, authorization: Annotated[str | None, Header()] = None):
    """Send content-free invalidation events, never private data across role boundaries."""

    # Streaming connections must not occupy a database pool slot for their lifetime.
    with SessionLocal() as db:
        from .dependencies import coordinator

        coordinator(current_user(db, authorization))

    async def stream():
        """Keep clients fresh without holding a database session during streaming."""
        while not await request.is_disconnected():
            yield 'event: refresh\ndata: {"refresh":true}\n\n'
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.include_router(response_router)


app.include_router(call_router)
