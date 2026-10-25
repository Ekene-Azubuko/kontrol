"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Activity,
  Ambulance,
  ArrowRight,
  Building2,
  ClipboardCheck,
  Clock3,
  Flame,
  Search,
} from "lucide-react";
import { useData } from "@/lib/api";
import type { Activity as ActivityRecord, Incident } from "@/lib/types";
import type {
  Dispatch,
  Hospital,
  ResponsePlan,
  Vehicle,
} from "@/lib/response-types";
import { time } from "@/lib/utils";
import { IncidentMap } from "./map";
import {
  Badge,
  Empty,
  ErrorBox,
  Loading,
  Metric,
  Panel,
  useAction,
} from "./shared";
import { PageHeading } from "./page-heading";
import { Button } from "./ui/button";
import { Drawer } from "./ui/dialog";
import { IncidentDetail } from "./incident-detail";
import { Calls } from "./calls";
import { AgentWorkspace } from "./agents";
import {
  PlanCard,
  PlanDetail,
  ResponsePlans,
  Workflow,
} from "./response-plans";
import {
  FleetWorkspace,
  networkMarkers,
} from "./network";

/** Route existing and new coordinator workspaces through the shared application shell. */
export function CoordinatorView({ page }: { page: string }) {
  if (page === "calls") return <Calls />;
  if (page === "response-plans") return <ResponsePlans />;
  if (page === "dispatch") return <FleetWorkspace />;
  if (page === "agents") return <AgentWorkspace />;
  return <CommandWorkspace register={page === "incidents"} />;
}

/** Keep the map, approval queue and response metrics grounded in live backend state. */
function CommandWorkspace({ register }: { register: boolean }) {
  const incidents = useData<Incident[]>("/incidents");
  const plans = useData<ResponsePlan[]>("/response-plans");
  const hospitals = useData<Hospital[]>("/hospitals");
  const fleet = useData<Vehicle[]>("/vehicles");
  const dispatches = useData<Dispatch[]>("/dispatches");
  const activity = useData<ActivityRecord[]>("/activity");
  const [selected, setSelected] = useState<string | null>(null);
  // Live queue updates must not open a review drawer without a dispatcher click.
  const [planId, setPlanId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [mapResponse, setMapResponse] = useState("all");
  const action = useAction();
  const active = (incidents.data || []).filter(
    (i) => !["completed", "cancelled", "rejected"].includes(i.response_status),
  );
  const awaiting = useMemo(
    () =>
      plans.data?.filter((p) =>
        ["awaiting_approval", "needs_information"].includes(p.status),
      ) || [],
    [plans.data],
  );
  const generating = plans.data?.filter((p) => p.status === "generating") || [];
  const tracked =
    generating[0] ||
    awaiting[0] ||
    plans.data?.find((p) => p.status === "approved");
  const ongoingPlans = (plans.data || []).filter(
    (plan) => plan.status === "approved",
  );
  const visiblePlanIds = new Set(
    ongoingPlans
      .filter((plan) => mapResponse === "all" || plan.id === mapResponse)
      .map((plan) => plan.id),
  );
  const visibleDispatches = (dispatches.data || []).filter(
    (dispatch) => visiblePlanIds.has(dispatch.plan_id) && !dispatch.released_at,
  );
  const visibleIncidentIds = new Set(
    visibleDispatches.map((dispatch) => dispatch.incident_id),
  );
  const visibleHospitalIds = new Set(
    visibleDispatches
      .map((dispatch) => dispatch.hospital_id)
      .filter((id): id is string => Boolean(id)),
  );
  const visibleVehicleIds = new Set(
    visibleDispatches.map((dispatch) => dispatch.vehicle_id),
  );
  const rows = (incidents.data || []).filter(
    (i) =>
      `${i.title} ${i.location}`.toLowerCase().includes(search.toLowerCase()) &&
      (filter === "all" || i.response_status === filter),
  );
  return (
    <>
      <PageHeading
        eyebrow="KONTROL COMMAND · LIVE OPERATIONS"
        title={register ? "Incidents" : "Command Center"}
        subtitle={
          register
            ? "Original observations, reported needs, and the response taking shape around them."
            : "One operational picture. From a reviewed call to an approved simulated response."
        }
      />
      {action.feedback}
      {incidents.error && <ErrorBox message={incidents.error.message} />}
      {!register && (
        <>
          <div className="metrics response-metrics">
            <Metric
              label="Active incidents"
              value={active.length}
              detail="Current reported incidents"
              icon={<Flame size={18} />}
            />
            <Metric
              label="Awaiting a plan"
              value={
                active.filter((i) =>
                  ["unplanned", "generating", "analysis_failed"].includes(
                    i.response_status,
                  ),
                ).length
              }
              detail={`${generating.length} generating now`}
              icon={<Clock3 size={18} />}
            />
            <Metric
              label="Needs review"
              value={awaiting.length}
              detail="Approval or more information"
              icon={<ClipboardCheck size={18} />}
              tone="amber"
            />
            <Metric
              label="Active dispatches"
              value={
                dispatches.data?.filter(
                  (d) => !d.released_at && d.status !== "cancelled",
                ).length || 0
              }
              detail="Assignments in progress"
              icon={<Activity size={18} />}
            />
            <Metric
              label="Available vehicles"
              value={
                fleet.data?.filter((v) => v.status === "available").length || 0
              }
              detail={`${fleet.data?.length || 0} units in the fleet`}
              icon={<Ambulance size={18} />}
            />
            <Metric
              label="Selected hospitals"
              value={visibleHospitalIds.size}
              detail="Destinations in approved plans"
              icon={<Building2 size={18} />}
            />
          </div>
          <div className="command-grid">
            <Panel
              title="San Francisco operational map"
              eyebrow="APPROVED RESPONSES"
              className="map-panel"
              action={
                <select
                  aria-label="Filter map by response"
                  value={mapResponse}
                  onChange={(event) => setMapResponse(event.target.value)}
                >
                  <option value="all">All ongoing responses</option>
                  {ongoingPlans.map((plan) => (
                    <option key={plan.id} value={plan.id}>
                      {plan.incident.title}
                    </option>
                  ))}
                </select>
              }
            >
              <IncidentMap
                items={networkMarkers(
                  active.filter((incident) => visibleIncidentIds.has(incident.id)),
                  (hospitals.data || []).filter((hospital) =>
                    visibleHospitalIds.has(hospital.id),
                  ),
                  (fleet.data || []).filter((vehicle) =>
                    visibleVehicleIds.has(vehicle.id),
                  ),
                )}
                fitToItems
                onSelect={(id) => setSelected(id)}
              />
            </Panel>
            <Panel
              title="Decision queue"
              eyebrow="YOUR NEXT ACTION"
              action={<span className="count">{awaiting.length}</span>}
            >
              <div className="decision-queue">
                {awaiting.slice(0, 3).map((plan) => (
                  <PlanCard
                    key={plan.id}
                    plan={plan}
                    onSelect={() => setPlanId(plan.id)}
                  />
                ))}
                {!awaiting.length && (
                  <Empty>
                    {generating.length
                      ? "Agents are preparing response plans."
                    : "No plans need review. Submit a report to begin."}
                  </Empty>
                )}
                <Link className="text-link" href="/coordinator/response-plans">
                  All response plans <ArrowRight size={15} />
                </Link>
              </div>
            </Panel>
          </div>
          <Panel
            title="Kontrol Agents"
            eyebrow="OBSERVABLE RESPONSE WORKFLOW"
            action={
              <Link className="text-link" href="/coordinator/agents">
                Agent Operations <ArrowRight size={14} />
              </Link>
            }
          >
            <div className="workflow-container">
              {tracked && (
                <div className="row">
                  <strong>{tracked.incident.title}</strong>
                  <Badge value={tracked.status} />
                </div>
              )}
              <Workflow
                runs={tracked?.runs}
                approved={!!tracked?.approved_at}
              />
              <small className="muted">
                Hospital and Dispatch evaluate in parallel. Every response waits
                for dispatcher approval.
              </small>
            </div>
          </Panel>
        </>
      )}
      <Panel
        title={register ? "Incident register" : "Current incidents"}
        action={<span className="count">{rows.length}</span>}
      >
        <div className="filter-row">
          <div className="search">
            <Search size={16} />
            <input
              aria-label="Search incidents"
              placeholder="Search incidents or locations…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <select
            aria-label="Response status"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">All response statuses</option>
            {[
              "unplanned",
              "generating",
              "awaiting_approval",
              "assigned",
              "en_route",
              "on_scene",
              "transporting",
              "completed",
              "rejected",
              "cancelled",
            ].map((status) => (
              <option value={status} key={status}>
                {status.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </div>
        {incidents.isLoading ? (
          <Loading />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Incident / location</th>
                  <th>Type</th>
                  <th>Reported injured</th>
                  <th>Response status</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, register ? 200 : 8).map((incident) => (
                  <tr key={incident.id}>
                    <td>
                      <button
                        className="table-title"
                        onClick={() => setSelected(incident.id)}
                      >
                        {incident.title}
                      </button>
                      <small>{incident.location}</small>
                    </td>
                    <td>
                      <Badge value={incident.category} />
                    </td>
                    <td>{incident.reported_casualties ?? "Unknown"}</td>
                    <td>
                      <Badge value={incident.response_status} />
                    </td>
                    <td>{time(incident.created_at)}</td>
                    <td>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setSelected(incident.id)}
                      >
                        View response <ArrowRight size={14} />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!rows.length && <Empty>No incidents match these filters.</Empty>}
          </div>
        )}
      </Panel>
      {!register && (
        <Panel title="Recent operational activity">
          <div className="activity-list">
            {activity.data?.slice(0, 6).map((item) => (
              <div className="activity-item" key={item.id}>
                <Activity size={16} />
                <div>
                  <strong>{item.action.replaceAll("_", " ")}</strong>
                  <p>{item.details}</p>
                </div>
                <small>{time(item.created_at)}</small>
              </div>
            ))}
            {!activity.data?.length && (
              <Empty>
                Coordinator decisions appear here.
              </Empty>
            )}
          </div>
        </Panel>
      )}
      <IncidentDetail
        id={selected && !selected.includes(":") ? selected : null}
        onClose={() => setSelected(null)}
      />
      <Drawer
        open={!!selected?.includes(":")}
        onClose={() => setSelected(null)}
        title="Network resource"
      >
        {selected?.startsWith("hospital:")
          ? hospitals.data
              ?.filter((h) => `hospital:${h.id}` === selected)
              .map((h) => (
                <div className="detail-section" key={h.id}>
                  <h1>{h.name}</h1>
                  <p>{h.location}</p>
                  <div className="resource-tags">
                    {h.capabilities.map((c) => (
                      <span key={c}>{c}</span>
                    ))}
                  </div>
                  <p className="muted">Facility details come from the Hospital agent. See the response plan for capacity findings and limitations.</p>
                </div>
              ))
          : fleet.data
              ?.filter((v) => `vehicle:${v.id}` === selected)
              .map((v) => (
                <div className="detail-section" key={v.id}>
                  <h1>{v.call_sign}</h1>
                  <Badge value={v.status} />
                  <p>{v.location}</p>
                  <div className="resource-tags">
                    {v.capabilities.map((c) => (
                      <span key={c}>{c.replaceAll("_", " ")}</span>
                    ))}
                  </div>
                  <Link className="button primary" href="/coordinator/dispatch">
                    Open Fleet & Dispatch
                  </Link>
                </div>
              ))}
      </Drawer>
      <PlanDetail id={planId} onClose={() => setPlanId(null)} />
    </>
  );
}
