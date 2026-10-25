"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  ArrowRight,
  Ambulance,
  Building2,
  Check,
  ClipboardCheck,
  GitBranch,
  ShieldCheck,
} from "lucide-react";
import { useData } from "@/lib/api";
import type { AgentRun } from "@/lib/types";
import type { RecordedCall, ResponsePlan, Vehicle } from "@/lib/response-types";
import { time } from "@/lib/utils";
import { Badge, Empty, ErrorBox, Loading, Panel, useAction } from "./shared";
import { PageHeading } from "./page-heading";
import { Button } from "./ui/button";
import { Drawer } from "./ui/dialog";
import { PlanHospitals } from "./plan-hospitals";
import { PlanReviewChecks } from "./plan-review-checks";
import { CallReopen } from "./call-reopen";

export const stages = [
  {
    key: "intake",
    name: "Incident Intake",
    description:
      "Extracts the report, location, injured count and broad response requirements.",
  },
  {
    key: "hospital",
    name: "Hospital",
    description:
      "Evaluates supplied beds, capabilities, diversion and travel estimates.",
  },
  {
    key: "dispatch",
    name: "Dispatch",
    description:
      "Evaluates supplied fleet availability, capabilities and current assignments.",
  },
  {
    key: "planning",
    name: "Response Planning",
    description:
      "Combines evaluated options into one plan for a dispatcher's decision.",
  },
];

/** Show persisted stage states and the parallel evaluation barrier. */
export function Workflow({
  runs = [],
  approved = false,
}: {
  runs?: AgentRun[];
  approved?: boolean;
}) {
  function node(stage: string) {
    const run = runs.find((item) => item.stage === stage);
    return (
      <div className={`workflow-node ${run?.status || "waiting"}`}>
        <span className="workflow-dot" />
        <span>
          {stages.find((s) => s.key === stage)?.name}
          <small>{run?.status || "waiting"}</small>
        </span>
        {run?.status === "completed" && <Check size={14} />}
      </div>
    );
  }
  return (
    <div className="workflow" aria-label="Response workflow">
      {node("intake")}
      <ArrowRight size={16} />
      <div className="workflow-parallel">
        <small>PARALLEL EVALUATION</small>
        {node("hospital")}
        {node("dispatch")}
      </div>
      <ArrowRight size={16} />
      {node("planning")}
      <ArrowRight size={16} />
      <div className={`workflow-node ${approved ? "completed" : "human"}`}>
        <ShieldCheck size={18} />
        <span>
          Dispatcher
          <small>{approved ? "approved" : "approval required"}</small>
        </span>
      </div>
    </div>
  );
}

/** Open a concise reviewable plan without editing agent-proposed resource allocations. */
export function PlanCard({
  plan,
  onSelect,
}: {
  plan: ResponsePlan;
  onSelect: () => void;
}) {
  return (
    <button className="plan-card" onClick={onSelect}>
      <div className="row">
        <Badge value={plan.status} />
        <span className="mono">
          REV {plan.revision} · {plan.id.slice(0, 6).toUpperCase()}
        </span>
      </div>
      <h3>{plan.incident.title}</h3>
      <p>{plan.summary}</p>
      <div className="plan-card-stats">
        <span>
          <Ambulance size={16} />
          {plan.assignments.length} units
        </span>
        <span>
          <Building2 size={16} />
          {
            new Set(plan.assignments.map((a) => a.hospital_id).filter(Boolean))
              .size
          }{" "}
          destinations
        </span>
        <span>
          {plan.requirements.estimated_patients ?? "—"} estimated patients
        </span>
      </div>
      <div className="row muted">
        <small>{plan.incident.location}</small>
        <span className="text-link">
          Review plan <ArrowRight size={14} />
        </span>
      </div>
    </button>
  );
}

/** Group plans by their actual lifecycle, preserving rejected revisions and reset history. */
export function ResponsePlans() {
  const query = useData<ResponsePlan[]>("/response-plans");
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const groups = [
    "generating",
    "awaiting_approval",
    "needs_information",
    "approved",
    "rejected",
    "completed",
    "failed",
    "cancelled",
  ];
  return (
    <>
      <PageHeading
        eyebrow="HUMAN DECISIONS · TRACEABLE RECOMMENDATIONS"
        title="Response Plans"
        subtitle="Review the evidence, compare resource options, and authorize the response."
      />
      <div className="response-intro">
        <ClipboardCheck size={24} />
        <div>
          <strong>Your decision starts the response.</strong>
          <p>
            Proposals do not reserve vehicles or beds. Approval checks current
            availability, creates assignments and updates the live map.
          </p>
        </div>
      </div>
      <div className="filter-row">
        <input
          className="plan-search"
          aria-label="Search response plans"
          placeholder="Search by incident or location…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          aria-label="Plan status"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">All plan statuses</option>
          {groups.map((status) => (
            <option value={status} key={status}>
              {status.replaceAll("_", " ")}
            </option>
          ))}
        </select>
      </div>
      {query.isLoading && <Loading />}
      {query.error && <ErrorBox message={query.error.message} />}
      {groups
        .filter((status) => filter === "all" || filter === status)
        .map((status) => {
          const plans =
            query.data?.filter(
              (plan) =>
                plan.status === status &&
                `${plan.incident.title} ${plan.incident.location}`
                  .toLowerCase()
                  .includes(search.toLowerCase()),
            ) || [];
          if (
            !plans.length &&
            filter === "all" &&
            status !== "awaiting_approval"
          )
            return null;
          return (
            <section className="plan-group" key={status}>
              <div className="plan-group-heading">
                <h2>{status.replaceAll("_", " ")}</h2>
                <span className="count">{plans.length}</span>
              </div>
              <div className="plan-grid">
                {plans.map((plan) => (
                  <PlanCard
                    key={plan.id}
                    plan={plan}
                    onSelect={() => setSelected(plan.id)}
                  />
                ))}
              </div>
              {!plans.length && (
                <Empty>
                  No {status.replaceAll("_", " ")} plans. New agent suggestions
                  appear here automatically.
                </Empty>
              )}
            </section>
          );
        })}
      <PlanDetail id={selected} onClose={() => setSelected(null)} />
    </>
  );
}

/** Keep vehicle alternatives compact, with each rationale available only when requested. */
function Alternatives({ run }: { run: AgentRun }) {
  const vehicles = (run.input.vehicles || []) as Vehicle[];
  const vehicleResults = run.output?.recommended_vehicles || [];
  const count = vehicleResults.length;
  return (
    <details className="alternatives">
      <summary>Vehicle options evaluated · {count}</summary>
      {vehicleResults.map((option) => {
        const vehicle = vehicles.find((row) => row.id === option.vehicle_id);
        return (
          <article key={option.vehicle_id} className="evidence">
            <div className="row">
              <strong>{vehicle?.call_sign || option.vehicle_id}</strong>
              <span className="mono">
                {option.estimated_arrival_minutes ?? "—"} min
              </span>
            </div>
            <small className="muted">
              {option.response_role.replaceAll("_", " ")} ·{" "}
              {option.starting_location} · {vehicle?.status || "unknown"}
            </small>
            <details className="agent-reasoning">
              <summary>Why this vehicle?</summary>
              <p>{option.reasoning}</p>
            </details>
          </article>
        );
      })}
      {!count && (
        <p className="muted">No suitable options recommended for this stage.</p>
      )}
      <details className="agent-reasoning">
        <summary>Full dispatch reasoning</summary>
        <p>{run.output?.reasoning}</p>
      </details>
    </details>
  );
}

/** Keep all decisions versioned and explicit; show assignments and progress after approval. */
export function PlanDetail({
  id,
  onClose,
  onCallReopened,
}: {
  id: string | null;
  onClose: () => void;
  onCallReopened?: (call: RecordedCall) => void;
}) {
  const router = useRouter();
  const query = useData<ResponsePlan>(`/response-plans/${id}`, !!id);
  const [note, setNote] = useState("");
  const action = useAction();
  const plan = query.data;
  async function decide(kind: "approve" | "reject" | "revise") {
    if (!plan) return;
    const decisionNote =
      kind === "approve" && note.trim().length < 3
        ? `Dispatcher approved the proposed response with its recorded constraints. ${note.trim()}`.trim()
        : note.trim();
    const result = await action.act<ResponsePlan>(
      `/response-plans/${plan.id}/decision`,
      {
        action: kind,
        version: plan.version,
        note: decisionNote,
      },
      "POST",
      kind === "approve"
        ? "Plan approved. Dispatch has started."
        : kind === "revise"
          ? "Revision requested. A new plan is generating."
          : "Plan rejected. No resources assigned.",
    );
    if (result) setNote("");
  }
  return (
    <Drawer open={!!id} onClose={onClose} title="Response plan review">
      {query.isLoading ? (
        <Loading />
      ) : query.error ? (
        <ErrorBox message={query.error.message} />
      ) : (
        plan && (
          <>
            <div className="detail-header">
              <div className="row">
                <Badge value={plan.status} />
                <span className="mono">
                  PLAN {plan.id.slice(0, 8).toUpperCase()} · REV {plan.revision}
                </span>
              </div>
              <h1>{plan.incident.title}</h1>
              <p className="muted">
                {plan.incident.location} · {time(plan.created_at)}
              </p>
            </div>
            <div className="detail-section">
              <Workflow runs={plan.runs} approved={!!plan.approved_at} />
              {plan.call && <CallReopen call={plan.call} onReopened={(call) => {
                onClose();
                if (onCallReopened) onCallReopened(call);
                else router.push(`/coordinator/calls?call=${encodeURIComponent(call.id)}`);
              }} />}
              <p className="plan-summary">
                {plan.status === "generating"
                  ? "Agents are preparing the response."
                  : `${plan.assignments.length} proposed units · ${new Set(plan.assignments.map((assignment) => assignment.hospital_id).filter(Boolean)).size} provisional hospital destinations`}
              </p>
              <PlanReviewChecks plan={plan} />
              <details className="agent-reasoning">
                <summary>Agent plan summary</summary>
                <p>{plan.summary}</p>
              </details>
              {!!plan.requirements.required_response_types?.length && (
                <>
                  <h3>Response requirements</h3>
                  <div className="resource-tags">
                    {plan.requirements.required_response_types.map((c) => (
                      <span key={c}>{c.replaceAll("_", " ")}</span>
                    ))}
                  </div>
                </>
              )}
              <h3>Proposed assignments</h3>
              {plan.assignments.map((assignment) => (
                <article className="assignment-card" key={assignment.id}>
                  <div className="row">
                    <strong>
                      <Ambulance size={18} /> {assignment.vehicle.call_sign}
                    </strong>
                    <span className="eta">
                      {assignment.vehicle_eta_minutes} min to scene ·{" "}
                      {assignment.vehicle_eta_method.replaceAll("_", " ")}
                    </span>
                  </div>
                  <details className="agent-reasoning">
                    <summary>Assignment rationale</summary>
                    <p>{assignment.reason}</p>
                  </details>
                  <div className="assignment-destination">
                    <Building2 size={16} />
                    <span>
                      {assignment.hospital?.name || "On-scene support"}
                      <small>
                        {assignment.patients
                          ? `${assignment.patients} patient(s) · ${assignment.hospital_eta_minutes} min scene → hospital`
                          : "No hospital beds reserved"}
                      </small>
                    </span>
                  </div>
                </article>
              ))}
              {!plan.assignments.length && (
                <Empty>
                  {plan.status === "generating"
                    ? "Agents are preparing the proposal."
                    : "No resource assignments proposed."}
                </Empty>
              )}
              <PlanHospitals key={plan.id} plan={plan} />
              {plan.call && (
                <details className="alternatives">
                  <summary>Call transcript provenance</summary>
                  <p>
                    Incident location: {plan.call.confirmed_address} ·{" "}
                    {plan.call.confirmed_latitude},{" "}
                    {plan.call.confirmed_longitude}
                  </p>
                  {plan.call.detected_location?.input_source ===
                    "dispatcher_address" && (
                    <p>
                      Address edited by dispatcher:{" "}
                      {plan.call.detected_location.input_address}. Coordinates
                      were located automatically.
                    </p>
                  )}
                  <p>
                    Approximate caller pin:{" "}
                    {plan.call.caller_latitude ?? "Unavailable"},{" "}
                    {plan.call.caller_longitude ?? "Unavailable"}
                  </p>
                  <details>
                    <summary>Original machine transcript</summary>
                    <p>{plan.call.original_transcript}</p>
                  </details>
                  <h4>Transcript used for response</h4>
                  <p>{plan.call.reviewed_transcript}</p>
                  <p className="muted">
                    Patient counts are unconfirmed estimates. Hospital
                    destinations are provisional.
                  </p>
                </details>
              )}
              <h3>Agent explanations & alternatives</h3>
              {plan.runs
                .filter((run) => run.output && run.stage !== "hospital")
                .map((run) =>
                  run.stage === "dispatch" ? (
                    <Alternatives key={run.id} run={run} />
                  ) : (
                    <details className="alternatives" key={run.id}>
                      <summary>
                        {stages.find((stage) => stage.key === run.stage)?.name}{" "}
                        details
                      </summary>
                      {run.output?.caller_stated_location && (
                        <p>
                          Caller-stated location:{" "}
                          {run.output.caller_stated_location}
                        </p>
                      )}
                      {run.output?.key_statements?.map((statement, index) => (
                        <blockquote key={index}>{statement}</blockquote>
                      ))}
                      <p>
                        {run.output?.summary ||
                          run.output?.plan_summary ||
                          run.output?.reasoning}
                      </p>
                    </details>
                  ),
                )}
              {plan.runs
                .filter((run) => run.error && run.status === "failed")
                .map((run) => (
                  <ErrorBox
                    key={run.id}
                    message={`${run.stage}: ${run.error}`}
                  />
                ))}
              {plan.status === "failed" && (
                <Link className="text-link" href="/coordinator/agents">
                  Review and retry failed stages in Agent Operations{" "}
                  <ArrowRight size={15} />
                </Link>
              )}
              {plan.dispatches.length > 0 && (
                <Panel title="Response progress">
                  {plan.dispatches.map((dispatch) => (
                    <div className="dispatch-mini" key={dispatch.id}>
                      <span>
                        {
                          plan.assignments.find(
                            (a) => a.vehicle_id === dispatch.vehicle_id,
                          )?.vehicle.call_sign
                        }
                      </span>
                      <Badge
                        value={
                          dispatch.released_at &&
                          dispatch.status !== "cancelled"
                            ? "available"
                            : dispatch.status
                        }
                      />
                      <progress max={1} value={dispatch.progress} />
                    </div>
                  ))}
                  <Link className="text-link" href="/coordinator/dispatch">
                    Watch fleet movement <ArrowRight size={14} />
                  </Link>
                </Panel>
              )}
              {plan.decision_note && (
                <div className="evidence">
                  <small>DISPATCHER DECISION</small>
                  <p>{plan.decision_note}</p>
                </div>
              )}
              {plan.revision > 1 && (
                <p className="muted">Revision request: {plan.revision_note}</p>
              )}
              {["awaiting_approval", "needs_information"].includes(
                plan.status,
              ) && (
                <div className="approval-box">
                  <h3>
                    <ShieldCheck size={20} /> Dispatcher decision
                  </h3>
                  <p>
                    {plan.feasible
                      ? "Approval reserves the proposed vehicles and hospital beds and adds the response to the live map."
                      : "You can approve the proposed response with its recorded constraints. Unconfirmed patient counts and bed availability remain pending."}
                  </p>
                  <label>
                    Decision or revision note (optional for approval)
                    <textarea
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      maxLength={1000}
                      placeholder="Record your review or describe the requested revision…"
                    />
                  </label>
                  <div className="decision-actions">
                    <Button
                      disabled={action.busy}
                      onClick={() => decide("approve")}
                    >
                      <Check size={16} />
                      Approve plan
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={action.busy || note.trim().length < 3}
                      onClick={() => decide("revise")}
                    >
                      <GitBranch size={16} />
                      Request revision
                    </Button>
                    <Button
                      variant="ghost"
                      disabled={action.busy || note.trim().length < 3}
                      onClick={() => decide("reject")}
                    >
                      Reject plan
                    </Button>
                  </div>
                </div>
              )}
              {action.feedback}
              <small className="muted">
                Agent recommendations require dispatcher approval before
                resources are assigned.
              </small>
            </div>
          </>
        )
      )}
    </Drawer>
  );
}
