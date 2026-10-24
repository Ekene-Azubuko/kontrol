"""Deterministic mock implementations of the four published CREAO contracts."""

from .response_schemas import DispatchResult, HospitalResult, IntakeResult, PlanningResult


def intake(payload: dict) -> IntakeResult:
    """Classify a report and preserve its explicit injury count."""
    report = payload["agent_input"]
    description = report["description"].lower()
    incident_type = (
        "building_collapse"
        if "collapse" in description
        else "fire"
        if "fire" in description
        else "collision"
        if "collid" in description
        else "road_obstruction"
    )
    responses = ["ambulance"] if (report["reported_injuries"] or 0) > 0 else []
    if incident_type in {"building_collapse", "fire", "collision", "road_obstruction"}:
        responses.append("fire_rescue")
    if not responses:
        responses.append("incident_support")
    return IntakeResult(
        incident_id=report["incident_id"],
        incident_type=incident_type,
        summary=report["description"][:2000],
        reported_injuries=report["reported_injuries"],
        required_response_types=responses,
        reasoning="Response types follow only the reported incident and injury information.",
    )


def hospital(payload: dict) -> HospitalResult:
    """Rank supplied mock hospitals while preserving unknown capacity."""
    agent_input = payload["agent_input"]
    rows = payload["hospitals"]
    candidates = [row for row in rows if not row["diversion"]]
    candidates.sort(key=lambda row: row["travel_minutes"])
    hospitals = [
        {
            "name": row["name"],
            "address": row["location"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "documented_capabilities": row["capabilities"],
            "available_beds": row["available_beds"],
            "diversion_status": row["diversion"],
            "estimated_travel_minutes": row["travel_minutes"],
            "travel_time_method": "coordinate_estimate",
            "source_urls": [],
            "suitability_notes": "Configured mock facility with relevant emergency services.",
        }
        for row in candidates[:8]
    ]
    return HospitalResult(
        incident_id=agent_input["incident_id"],
        hospitals=hospitals,
        recommended_hospitals=[row["name"] for row in hospitals[:3]],
        reasoning="Candidates are ordered by the deterministic coordinate estimate.",
        limitations=[] if hospitals else ["No suitable hospital record is available."],
    )


def dispatch(payload: dict) -> DispatchResult:
    """Recommend available mock fleet records without inventing vehicles."""
    agent_input = payload["agent_input"]
    rows = {row["id"]: row for row in payload["vehicles"]}
    available = agent_input["available_vehicles"]
    recommendations = []
    for response_type in agent_input["required_response_types"]:
        match = next(
            (
                row
                for row in available
                if row["vehicle_id"] not in {item["vehicle_id"] for item in recommendations}
                and (
                    response_type in row["type"]
                    or response_type in row["capabilities"]
                    or (response_type == "ambulance" and row["type"] == "ambulance")
                    or (response_type == "fire_rescue" and row["type"] in {"fire_engine", "rescue_unit"})
                )
            ),
            None,
        )
        if match:
            recommendations.append(
                {
                    "vehicle_id": match["vehicle_id"],
                    "response_role": response_type,
                    "starting_location": match["base_location"],
                    "estimated_arrival_minutes": rows[match["vehicle_id"]]["travel_minutes"],
                    "reasoning": "Available configured vehicle matching the response role.",
                }
            )
    filled = {row["response_role"] for row in recommendations}
    missing = [role for role in agent_input["required_response_types"] if role not in filled]
    return DispatchResult(
        incident_id=agent_input["incident_id"],
        discovered_facilities=[],
        recommended_vehicles=recommendations,
        unfilled_requirements=missing,
        reasoning="Recommendations reference only available configured vehicles.",
        limitations=[] if not missing else ["Some response roles have no available matching vehicle."],
    )


def planning(payload: dict) -> PlanningResult:
    """Combine deterministic findings into the published planning contract."""
    agent_input = payload["agent_input"]
    intake_result = agent_input["intake_result"]
    hospital_result = agent_input["hospital_result"]
    dispatch_result = agent_input["dispatch_result"]
    injuries = intake_result["reported_injuries"]
    hospitals = hospital_result["recommended_hospitals"]
    vehicles = dispatch_result["recommended_vehicles"]
    unfilled = list(dispatch_result["unfilled_requirements"])
    constraints = list(hospital_result["limitations"]) + list(dispatch_result["limitations"])
    if injuries is None:
        constraints.append("The number of patients is unknown.")
    if (injuries or 0) > 0 and not hospitals:
        unfilled.append("receiving_hospital")
    hospital_capacity = sum(
        row["available_beds"] or 0
        for row in hospital_result["hospitals"]
        if row["name"] in hospitals
    )
    vehicle_capacity = sum(
        row["patient_capacity"]
        for row in payload["vehicles"]
        if row["id"] in {vehicle["vehicle_id"] for vehicle in vehicles}
    )
    if injuries is not None and injuries > min(hospital_capacity, vehicle_capacity):
        unfilled.append("patient_transport_capacity")
    status = "awaiting_approval" if vehicles and not unfilled and injuries is not None else "needs_information"
    return PlanningResult(
        incident_id=agent_input["incident_id"],
        plan_summary=f"Proposed {len(vehicles)}-vehicle response for {intake_result['incident_type']}.",
        hospital_assignments=(
            [
                {
                    "hospital_name": hospitals[0],
                    "planned_patient_count": injuries,
                    "reasoning": "Recommended destination from the Hospital Finder.",
                }
            ]
            if hospitals and (injuries or 0) > 0
            else []
        ),
        vehicle_assignments=[
            {
                "vehicle_id": row["vehicle_id"],
                "response_role": row["response_role"],
                "destination": (
                    hospitals[0] if hospitals and row["response_role"] == "ambulance" else "incident location"
                ),
                "reasoning": row["reasoning"],
            }
            for row in vehicles
        ],
        unfilled_requirements=unfilled,
        constraints=constraints,
        reasoning="The proposal combines the three validated upstream agent results.",
        status=status,
    )
