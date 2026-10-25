import type { AgentRun } from "../lib/types";
import type { DiscoveredHospital, ResponsePlan } from "../lib/response-types";

/** Supply fictional, deliberately verbose output with recommendation order opposite to proximity. */
export function reviewFixture(): ResponsePlan {
  /** Vary only latitude so proximity is independent of recommendations and travel estimates. */
  const hospital = (name: string, latitude: number): DiscoveredHospital => ({
    name,
    address: `${name} exercise address`,
    latitude,
    longitude: -122.42,
    documented_capabilities: ["emergency_department"],
    available_beds: null,
    diversion_status: null,
    estimated_travel_minutes: null,
    travel_time_method: "unavailable",
    source_urls: [],
    suitability_notes: `Detailed suitability for ${name}. `.repeat(12),
  });
  /** Wrap fixture output in the persisted agent-run shape without executing an agent. */
  const run = (stage: string, output: AgentRun["output"]): AgentRun => ({
    id: `run-${stage}`,
    incident_id: "incident",
    report_id: "report",
    plan_id: "review-fixture",
    stage,
    status: "completed",
    attempts: 1,
    started_at: null,
    completed_at: null,
    created_at: "2026-10-24T12:00:00Z",
    input: {},
    output,
    raw_response: null,
    error: null,
  });
  return {
    id: "review-fixture",
    incident_id: "incident",
    report_source: "911_call",
    call: null,
    incident: {
      id: "incident",
      title: "SIM · Hospital comparison exercise",
      category: "collision",
      severity: "high",
      latitude: 37.78,
      longitude: -122.42,
      location: "Fictional exercise intersection",
      summary: "Simulation only",
      status: "unverified",
      version: 1,
      created_at: "2026-10-24T12:00:00Z",
      assigned_to: null,
      reported_casualties: null,
      response_status: "needs_information",
    },
    status: "needs_information",
    revision: 1,
    revision_note: "Initial exercise",
    summary: "Full agent plan narrative. ".repeat(60),
    requirements: {
      estimated_patients: null,
      required_response_types: ["ambulance"],
    },
    constraints: Array.from(
      { length: 23 },
      (_, index) =>
        `Recorded limitation ${index + 1}: retain the complete original explanation for review.`,
    ),
    feasible: false,
    version: 1,
    created_at: "2026-10-24T12:00:00Z",
    approved_at: null,
    completed_at: null,
    decision_note: null,
    assignments: [],
    dispatches: [],
    runs: [
      run("hospital", {
        hospitals: [
          hospital("SIM · Far Hospital", 37.81),
          hospital("SIM · Near Hospital", 37.781),
          hospital("SIM · Middle Hospital", 37.79),
        ],
        recommended_hospitals: ["SIM · Far Hospital", "SIM · Middle Hospital"],
        reasoning: "Full hospital evaluation narrative. ".repeat(90),
        limitations: ["Bed availability is unknown."],
      }),
      run("dispatch", {
        unfilled_requirements: ["No accessible rescue unit was supplied."],
        recommended_vehicles: [],
      }),
    ],
  };
}
