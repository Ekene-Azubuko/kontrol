"""Authoritative operational records; agent findings never confer approval."""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, now


class User(Base):
    """A named principal with a server-enforced role."""

    __tablename__ = "users"
    name: Mapped[str]
    role: Mapped[str]
    token_hash: Mapped[str] = mapped_column(unique=True)


class Incident(Base):
    """A consolidated claim with independently controlled official status."""

    __tablename__ = "incidents"
    title: Mapped[str]
    category: Mapped[str]
    severity: Mapped[str] = mapped_column(default="moderate")
    status: Mapped[str] = mapped_column(default="needs_review")
    latitude: Mapped[float]
    longitude: Mapped[float]
    location: Mapped[str]
    summary: Mapped[str] = mapped_column(default="Awaiting intake assessment")
    reported_casualties: Mapped[int | None]
    response_status: Mapped[str] = mapped_column(default="unplanned")
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    merged_into: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"))
    version: Mapped[int] = mapped_column(default=1)
    simulation: Mapped[bool] = mapped_column(default=False)
    __mapper_args__ = {"version_id_col": version}


class Report(Base):
    """Private original observations with source and processing provenance."""

    __tablename__ = "reports"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str]
    description: Mapped[str]
    reported_casualties: Mapped[int | None]
    latitude: Mapped[float]
    longitude: Mapped[float]
    location: Mapped[str]
    observed_at: Mapped[datetime]
    photo: Mapped[str | None]
    source: Mapped[str] = mapped_column(default="resident")
    status: Mapped[str] = mapped_column(default="queued")
    simulation: Mapped[bool] = mapped_column(default=False)


class IncidentReport(Base):
    """Preserve report associations when coordinators consolidate incidents."""

    __tablename__ = "incident_reports"
    __table_args__ = (UniqueConstraint("incident_id", "report_id"),)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"))


class Evidence(Base):
    """A traceable piece of evidence, with uncertainty explicitly retained."""

    __tablename__ = "evidence"
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"))
    text: Mapped[str]
    source: Mapped[str]
    uncertainty: Mapped[str]


class Resource(Base):
    """Coordinator-maintained fictional resource availability."""

    __tablename__ = "resources"
    name: Mapped[str]
    category: Mapped[str]
    location: Mapped[str]
    latitude: Mapped[float]
    longitude: Mapped[float]
    capacity: Mapped[int]
    occupancy: Mapped[int]
    accessible: Mapped[bool] = mapped_column(default=True)
    pet_friendly: Mapped[bool] = mapped_column(default=False)
    contact: Mapped[str] = mapped_column(default="SIMULATION — no real contact")
    published: Mapped[bool] = mapped_column(default=True)
    confirmed_at: Mapped[datetime] = mapped_column(default=now)
    version: Mapped[int] = mapped_column(default=1)
    __mapper_args__ = {"version_id_col": version}


class ResourceRequest(Base):
    """A proposed allocation requiring a coordinator's explicit approval."""

    __tablename__ = "resource_requests"
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"))
    quantity: Mapped[int]
    status: Mapped[str] = mapped_column(default="pending")
    rationale: Mapped[str]
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class PublicUpdate(Base):
    """A versioned message whose approved snapshot is safe for residents."""

    __tablename__ = "public_updates"
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    title: Mapped[str]
    body: Mapped[str]
    audience: Mapped[str]
    status: Mapped[str] = mapped_column(default="draft")
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None]
    latitude: Mapped[float]
    longitude: Mapped[float]
    category: Mapped[str]
    severity: Mapped[str]
    simulation: Mapped[bool] = mapped_column(default=True)


class AgentRun(Base):
    """A durable queue item and actual execution record for one agent stage."""

    __tablename__ = "agent_runs"
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"))
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("response_plans.id"), index=True)
    stage: Mapped[str]
    __table_args__ = (UniqueConstraint("plan_id", "stage"),)
    status: Mapped[str] = mapped_column(default="queued")
    attempts: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict | None] = mapped_column(JSON)
    raw_response: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None]
    remote_id: Mapped[str | None]


class AgentFinding(Base):
    """Schema-validated assessment linked to its execution and incident."""

    __tablename__ = "agent_findings"
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), unique=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    assessment: Mapped[dict] = mapped_column(JSON)


class CoordinatorAction(Base):
    """Append-only record of human approval and incident state transitions."""

    __tablename__ = "coordinator_actions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"))
    action: Mapped[str]
    details: Mapped[str]


class Subscription(Base):
    """An individual resident's followed public incidents."""

    __tablename__ = "incident_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "incident_id"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))


class Simulation(Base):
    """Durable replay cursor, controlled under a database row lock."""

    __tablename__ = "simulation"
    running: Mapped[bool] = mapped_column(default=False)
    cursor: Mapped[int] = mapped_column(default=0)
    speed: Mapped[int] = mapped_column(default=1)
    last_event_at: Mapped[datetime] = mapped_column(default=now)
    worker_heartbeat: Mapped[datetime] = mapped_column(default=now)


class Hospital(Base):
    """A discovered or operator-configured hospital with separately authoritative capacity."""

    __tablename__ = "hospitals"
    name: Mapped[str]
    location: Mapped[str]
    latitude: Mapped[float]
    longitude: Mapped[float]
    capabilities: Mapped[list[str]] = mapped_column(JSON)
    total_beds: Mapped[int | None]
    occupied_beds: Mapped[int | None]
    reserved_beds: Mapped[int] = mapped_column(default=0)
    baseline_occupied: Mapped[int | None]
    diversion: Mapped[bool] = mapped_column(default=False)
    simulation: Mapped[bool] = mapped_column(default=True)
    source_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    discovered_by_agent: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(default=1)
    __mapper_args__ = {"version_id_col": version}


class HospitalInventory(Base):
    """Small simulated medicine and equipment inventory with low-stock thresholds."""

    __tablename__ = "hospital_inventory"
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id"))
    name: Mapped[str]
    category: Mapped[str]
    quantity: Mapped[int]
    low_stock_threshold: Mapped[int]


class EmergencyVehicle(Base):
    """Simulated fleet unit whose position and availability are backend-owned."""

    __tablename__ = "emergency_vehicles"
    call_sign: Mapped[str] = mapped_column(unique=True)
    vehicle_type: Mapped[str]
    capabilities: Mapped[list[str]] = mapped_column(JSON)
    patient_capacity: Mapped[int]
    status: Mapped[str] = mapped_column(default="available")
    latitude: Mapped[float]
    longitude: Mapped[float]
    home_latitude: Mapped[float]
    home_longitude: Mapped[float]
    location: Mapped[str]
    home_location: Mapped[str]
    simulation: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(default=1)
    __mapper_args__ = {"version_id_col": version}


class ResponsePlan(Base):
    """A proposed response and its human decision, independent of legacy verification."""

    __tablename__ = "response_plans"
    __table_args__ = (UniqueConstraint("incident_id", "revision"),)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"))
    status: Mapped[str] = mapped_column(default="generating")
    revision: Mapped[int] = mapped_column(default=1)
    revision_note: Mapped[str] = mapped_column(default="Initial response assessment")
    summary: Mapped[str] = mapped_column(default="Awaiting agent assessment")
    requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    constraints: Mapped[list[str]] = mapped_column(JSON, default=list)
    feasible: Mapped[bool] = mapped_column(default=False)
    decision_note: Mapped[str | None]
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(default=1)
    simulation: Mapped[bool] = mapped_column(default=False)
    __mapper_args__ = {"version_id_col": version}


class ProposedAssignment(Base):
    """Validated agent proposal; does not reserve resources until approval."""

    __tablename__ = "proposed_assignments"
    __table_args__ = (UniqueConstraint("plan_id", "vehicle_id"),)
    plan_id: Mapped[str] = mapped_column(ForeignKey("response_plans.id"))
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("emergency_vehicles.id"))
    hospital_id: Mapped[str | None] = mapped_column(ForeignKey("hospitals.id"))
    patients: Mapped[int | None]
    vehicle_eta_minutes: Mapped[float]
    hospital_eta_minutes: Mapped[float | None]
    vehicle_eta_method: Mapped[str] = mapped_column(default="coordinate_estimate")
    hospital_eta_method: Mapped[str | None]
    response_role: Mapped[str] = mapped_column(default="response")
    reason: Mapped[str]


class DispatchAssignment(Base):
    """Approved simulated movement with explicit lifecycle and arrival bookkeeping."""

    __tablename__ = "dispatch_assignments"
    __table_args__ = (UniqueConstraint("plan_id", "vehicle_id"),)
    plan_id: Mapped[str] = mapped_column(ForeignKey("response_plans.id"))
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("emergency_vehicles.id"))
    hospital_id: Mapped[str | None] = mapped_column(ForeignKey("hospitals.id"))
    patients: Mapped[int]
    status: Mapped[str] = mapped_column(default="assigned")
    stage_started_at: Mapped[datetime] = mapped_column(default=now)
    origin_latitude: Mapped[float]
    origin_longitude: Mapped[float]
    progress: Mapped[float] = mapped_column(default=0)
    completed_at: Mapped[datetime | None]
    released_at: Mapped[datetime | None]


class CommunicationLog(Base):
    """Internal simulated messages only; no external messaging service is called."""

    __tablename__ = "communication_logs"
    plan_id: Mapped[str] = mapped_column(ForeignKey("response_plans.id"))
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"))
    recipient: Mapped[str]
    recipient_type: Mapped[str]
    message: Mapped[str]
    status: Mapped[str] = mapped_column(default="sent")
    acknowledged_at: Mapped[datetime | None]
    simulation: Mapped[bool] = mapped_column(default=False)
