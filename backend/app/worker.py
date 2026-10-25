"""Durable four-agent workflow with parallel evaluations and independent dispatch ticks."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from sqlalchemy import case, select
from .agent_errors import agent_error_message
from .config import settings
from .demo_fleet import vehicle_enabled
from .creao import get_adapter
from .hospital_discovery import store_discovered_hospitals
from .db import SessionLocal, now
from .models import (
    AgentFinding,
    AgentRun,
    Evidence,
    Hospital,
    Incident,
    ProposedAssignment,
    Report,
    ResponsePlan,
    Simulation,
)
from .network import hospitals, operation_lock, travel_minutes, vehicles
from .response_schemas import stage_schema
from .response_services import update_response_status, validate_stage


def job_payload(db, run: AgentRun) -> dict:
    """Build the smallest stage-specific input while retaining validation snapshots internally."""
    report = db.get(Report, run.report_id)
    incident = db.get(Incident, run.incident_id)
    plan = db.get(ResponsePlan, run.plan_id)
    prior = list(db.scalars(select(AgentRun).where(AgentRun.plan_id == plan.id, AgentRun.id != run.id)))
    findings = {
        row.stage: row.output
        if row.status == "completed"
        else {"status": row.status, "error": row.error or "Agent did not complete"}
        for row in prior
        if row.status in {"completed", "failed", "cancelled"}
    }
    include_simulation = settings.creao_mode == "mock" or settings.live_simulation_enabled
    # Intake needs no resources, and Hospital must not depend on fleet reads.
    # Planning's resource snapshots stay local for validation; only agent_input goes to CREAO.
    hospital_rows = (
        [row for row in hospitals(db, incident) if include_simulation or not row["simulation"]]
        if run.stage in {"hospital", "planning"}
        else []
    )
    vehicle_rows = (
        [row for row in vehicles(db, incident) if vehicle_enabled(row["id"], row["simulation"])]
        if run.stage in {"dispatch", "planning"}
        else []
    )
    location = {
        "address": incident.location,
        "latitude": incident.latitude,
        "longitude": incident.longitude,
    }
    if run.stage == "intake":
        agent_input = {
            "incident_id": report.id,
            "transcript": report.description,
            "confirmed_location": location,
            "call_received_at": report.observed_at.isoformat(),
            "category": report.category,
        }
    elif run.stage == "hospital":
        intake = findings["intake"]
        agent_input = {
            "incident_id": report.id,
            "incident_type": intake["incident_type"],
            "incident_location": location,
            "reported_injuries": intake["reported_injuries"],
            "required_hospital_capabilities": (
                ["emergency_department"] if (intake["reported_injuries"] or 0) > 0 else []
            ),
            "search_radius_miles": 15,
            "hospital_statuses": [
                {
                    "hospital_id": row["id"],
                    "name": row["name"],
                    "available_beds": row["available_beds"],
                    "diversion_status": row["diversion"],
                }
                for row in hospital_rows
            ],
        }
    elif run.stage == "dispatch":
        intake = findings["intake"]
        agent_input = {
            "incident_id": report.id,
            "incident_type": intake["incident_type"],
            "incident_location": location,
            "required_response_types": intake["required_response_types"],
            "search_radius_miles": 10,
            "available_vehicles": [
                {
                    "vehicle_id": row["id"],
                    "type": row["vehicle_type"],
                    "status": row["status"],
                    "capabilities": row["capabilities"],
                    "base_location": row["home_location"],
                    "current_latitude": row["latitude"],
                    "current_longitude": row["longitude"],
                }
                for row in vehicle_rows
                if row["status"] == "available" and not row["assignment"]
            ],
        }
    else:
        agent_input = {
            "incident_id": report.id,
            "intake_result": findings["intake"],
            "hospital_result": findings["hospital"],
            "dispatch_result": findings["dispatch"],
        }
    payload = {
        "job_id": run.id,
        "remote_id": run.remote_id,
        "stage": run.stage,
        "revision_note": plan.revision_note,
        "agent_input": agent_input,
        "findings": findings,
    }
    if run.stage in {"hospital", "planning"}:
        payload["hospitals"] = hospital_rows
    if run.stage in {"dispatch", "planning"}:
        payload["vehicles"] = vehicle_rows
    return payload


def finish_stage(db, run: AgentRun, output: dict) -> None:
    """Persist findings and cross the parallel barrier once, under the plan's lock."""
    plan = db.get(ResponsePlan, run.plan_id)
    incident = db.get(Incident, run.incident_id)
    if run.stage == "hospital":
        for hospital in output["hospitals"]:
            if hospital["estimated_travel_minutes"] is None:
                hospital["estimated_travel_minutes"] = travel_minutes(
                    incident.latitude,
                    incident.longitude,
                    hospital["latitude"],
                    hospital["longitude"],
                )
                hospital["travel_time_method"] = "coordinate_estimate"
            elif hospital["travel_time_method"] is None:
                notes = hospital["suitability_notes"].lower()
                hospital["travel_time_method"] = (
                    "road_routing" if "road routing" in notes or "osrm" in notes else "coordinate_estimate"
                )
    if run.stage == "dispatch":
        vehicle_lookup = {row["id"]: row for row in run.input["vehicles"]}
        for recommendation in output["recommended_vehicles"]:
            if recommendation["estimated_arrival_minutes"] is None:
                recommendation["estimated_arrival_minutes"] = vehicle_lookup[
                    recommendation["vehicle_id"]
                ]["travel_minutes"]
    if run.stage == "hospital":
        store_discovered_hospitals(db, output["hospitals"])
    run.output, run.status, run.completed_at, run.error = output, "completed", now(), None
    db.add(AgentFinding(run_id=run.id, incident_id=run.incident_id, assessment=output))
    if run.stage == "intake":
        plan.requirements = {
            "estimated_patients": output["reported_injuries"],
            "required_response_types": output["required_response_types"],
            "patient_count_verification": "unconfirmed_agent_estimate",
        }
        incident.summary, incident.category = (
            output["summary"],
            output["incident_type"],
        )
        db.add(
            Evidence(
                incident_id=incident.id,
                report_id=run.report_id,
                text=output["summary"],
                source="911 call transcript / agent extraction",
                uncertainty=output["reasoning"],
            )
        )
        for stage in ["hospital", "dispatch"]:
            db.add(AgentRun(report_id=run.report_id, incident_id=incident.id, plan_id=plan.id, stage=stage))
    elif run.stage in {"hospital", "dispatch"}:
        db.flush()
        queue_planning_if_ready(db, run, incident)
    elif run.stage == "planning":
        plan.summary = output["plan_summary"]
        plan.feasible = output["status"] == "awaiting_approval" and not output["unfilled_requirements"]
        plan.constraints = list(dict.fromkeys(
            plan.constraints + output["constraints"] + output.get("limitations", []) + output["unfilled_requirements"]
            + run.input["findings"]["intake"].get("limitations", [])
        ))
        # Older completed Hospital jobs may predate discovery persistence; recover missing destinations on retry.
        store_discovered_hospitals(db, run.input["findings"]["hospital"].get("hospitals", []), refresh_existing=False)
        hospital_query = select(Hospital)
        if settings.creao_mode == "live" and not settings.live_simulation_enabled:
            hospital_query = hospital_query.where(Hospital.simulation.is_(False))
        hospital_by_name = {row.name.casefold(): row for row in db.scalars(hospital_query)}
        vehicle_snapshot = {v["id"]: v for v in run.input["vehicles"]}
        hospital_outputs = {
            row["name"].casefold(): row
            for row in run.input["findings"]["hospital"].get("hospitals", [])
        }
        hospital_assignments = output["hospital_assignments"]
        available_ids = {
            row["id"] for row in run.input["vehicles"] if row["status"] == "available" and not row["assignment"]
        }
        if any(row["vehicle_id"] not in available_ids for row in output["vehicle_assignments"]):
            plan.feasible = False
            plan.status = "needs_information"
            plan.constraints = [
                *plan.constraints,
                "A recommended vehicle became unavailable before planning completed.",
            ]
            update_response_status(db, incident, "needs_information")
            return
        transport_assigned = False
        for assignment in output["vehicle_assignments"]:
            destination = None
            if hospital_assignments and not transport_assigned and assignment["response_role"] == "ambulance":
                destination = hospital_assignments[0]
                transport_assigned = True
            hospital = hospital_by_name.get(destination["hospital_name"].casefold()) if destination else None
            hospital_output = hospital_outputs.get(destination["hospital_name"].casefold()) if destination else None
            vehicle = vehicle_snapshot[assignment["vehicle_id"]]
            db.add(
                ProposedAssignment(
                    plan_id=plan.id,
                    vehicle_id=assignment["vehicle_id"],
                    hospital_id=hospital.id if hospital else None,
                    patients=destination["planned_patient_count"] if destination else 0,
                    reason=assignment["reasoning"],
                    response_role=assignment["response_role"],
                    vehicle_eta_minutes=vehicle["travel_minutes"],
                    vehicle_eta_method="coordinate_estimate",
                    hospital_eta_minutes=(hospital_output or {}).get("estimated_travel_minutes"),
                    hospital_eta_method=(hospital_output or {}).get("travel_time_method"),
                )
            )
        plan.status = output["status"]
        update_response_status(db, incident, output["status"])


def queue_planning_if_ready(db, run: AgentRun, incident: Incident) -> None:
    """Queue planning only when both parallel evaluations completed successfully."""
    terminal = {"completed", "failed", "cancelled"}
    parallel = list(
        db.scalars(
            select(AgentRun).where(
                AgentRun.plan_id == run.plan_id,
                AgentRun.stage.in_(["hospital", "dispatch"]),
            )
        )
    )
    if len(parallel) != 2 or not all(item.status in terminal for item in parallel):
        return
    plan = db.get(ResponsePlan, run.plan_id)
    if any(item.status != "completed" for item in parallel):
        plan.status = "failed"
        update_response_status(db, incident, "analysis_failed")
        return
    if not db.scalar(select(AgentRun).where(AgentRun.plan_id == run.plan_id, AgentRun.stage == "planning")):
        db.add(
            AgentRun(
                report_id=run.report_id,
                incident_id=incident.id,
                plan_id=run.plan_id,
                stage="planning",
            )
        )


def recover_expired(db) -> None:
    """Fail expired leases for explicit human retry without risking duplicate live execution."""
    for run in db.scalars(
        select(AgentRun)
        .where(
            AgentRun.status == "running",
            AgentRun.started_at < now() - timedelta(seconds=settings.creao_timeout + 60),
        )
        .with_for_update(skip_locked=True)
    ):
        run.status, run.error, run.completed_at = (
            "failed",
            "Worker lease expired; review before manual retry",
            now(),
        )
        if run.plan_id:
            plan = db.get(ResponsePlan, run.plan_id)
            plan.status = "failed"
            update_response_status(db, db.get(Incident, run.incident_id), "analysis_failed")


def process_one() -> bool:
    """Claim a durable stage, invoke without locks and atomically persist a validated result."""
    with SessionLocal() as db:
        query = (
            select(AgentRun)
            .join(Report, AgentRun.report_id == Report.id)
            .join(ResponsePlan, AgentRun.plan_id == ResponsePlan.id)
            .where(AgentRun.status == "queued", ResponsePlan.status == "generating")
        )
        if settings.creao_mode == "live" and not settings.live_simulation_enabled:
            query = query.where(Report.simulation.is_(False))
        run = db.scalar(
            query.order_by(case((Report.simulation.is_(False), 0), else_=1), AgentRun.created_at)
            .with_for_update(skip_locked=True, of=AgentRun)
            .limit(1)
        )
        if not run:
            return False
        run.input = job_payload(db, run)
        # JSON payloads must not contain database datetime objects.
        import json

        run.input = json.loads(json.dumps(run.input, default=str))
        run.status, run.started_at, run.attempts = "running", now(), run.attempts + 1
        db.get(Report, run.report_id).status = "analyzing"
        db.commit()
        run_id, plan_id, stage, payload = run.id, run.plan_id, run.stage, run.input
    adapter = None
    try:
        adapter = get_adapter()
        result = adapter.invoke(stage, payload)
        output = (
            stage_schema(stage)
            .model_validate(result.model_dump() if hasattr(result, "model_dump") else result)
            .model_dump()
        )
        validate_stage(stage, output, payload)
        with SessionLocal() as db:
            operation_lock(db)
            plan = db.scalar(select(ResponsePlan).where(ResponsePlan.id == plan_id).with_for_update())
            run = db.get(AgentRun, run_id)
            # Reset or a failed sibling may have stopped the workflow while the remote call ran.
            if run.status != "running" or plan.status not in {"generating", "failed"}:
                return True
            run.remote_id = getattr(adapter, "remote_id", None)
            run.raw_response = getattr(adapter, "raw_response", None)
            finish_stage(db, run, output)
            db.commit()
    except Exception as exc:
        logging.exception("Agent stage failed: %s", stage)
        with SessionLocal() as db:
            operation_lock(db)
            run = db.get(AgentRun, run_id)
            if run and run.status == "running":
                run.remote_id = getattr(adapter, "remote_id", None)
                run.raw_response = getattr(adapter, "raw_response", None)
                run.status, run.completed_at = "failed", now()
                run.error = agent_error_message(stage, exc)
                plan = db.get(ResponsePlan, plan_id)
                incident = db.get(Incident, run.incident_id)
                if stage in {"hospital", "dispatch"}:
                    queue_planning_if_ready(db, run, incident)
                else:
                    plan.status = "failed"
                    update_response_status(db, incident, "analysis_failed")
                db.commit()
    return True


def main() -> None:
    """Keep two agent slots available while advancing simulation independently of remote latency."""
    from .dispatch_simulation import dispatch_tick
    from .seed import simulation_tick

    logging.basicConfig(level=logging.INFO)
    from .call_worker import process_one_call, recover_expired_calls

    with (ThreadPoolExecutor(max_workers=2, thread_name_prefix="kontrol-agent") as executor,
          ThreadPoolExecutor(max_workers=1, thread_name_prefix="kontrol-transcription") as transcription):
        pending = []
        call_future = None
        while True:
            try:
                finished = [future for future in pending if future.done()]
                pending = [future for future in pending if not future.done()]
                for future in finished:
                    future.result()
                with SessionLocal() as db:
                    state = db.scalar(select(Simulation).with_for_update())
                    if state:
                        state.worker_heartbeat = now()
                        simulation_tick(db, state)
                    recover_expired(db)
                    recover_expired_calls(db)
                    dispatch_tick(db)
                    db.commit()
                if call_future is None or call_future.done():
                    finished_call, call_future = call_future, None
                    # Clear a failed future before observing its error so a transient DB failure
                    # cannot permanently disable the transcription slot.
                    if finished_call is not None:
                        finished_call.result()
                    call_future = transcription.submit(process_one_call)
                while len(pending) < 2:
                    pending.append(executor.submit(process_one))
            except Exception:
                logging.exception("Worker iteration failed")
            time.sleep(max(0.1, settings.worker_interval))


if __name__ == "__main__":
    main()
