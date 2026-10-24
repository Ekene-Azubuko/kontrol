"use client";
import { useState } from "react";
import { Building2, List, Map, Search, Users, Warehouse } from "lucide-react";
import { useData } from "@/lib/api";
import type {
  AgentRun,
  Incident,
  Resource,
  ResourceRequest,
} from "@/lib/types";
import {
  Badge,
  Empty,
  ErrorBox,
  Metric,
  Panel,
  ResourceCard,
  useAction,
} from "./shared";
import { PageHeading } from "./page-heading";
import { IncidentMap } from "./map";
import { Button } from "./ui/button";
import { Drawer } from "./ui/dialog";

/** Share the published directory while keeping capacity and allocation controls coordinator-only. */
export function ResourceWorkspace({
  coordinator = false,
}: {
  coordinator?: boolean;
}) {
  const resources = useData<Resource[]>("/resources");
  const agentRuns = useData<AgentRun[]>("/agents", coordinator);
  const requests = useData<ResourceRequest[]>(
    "/resource-requests",
    coordinator,
  );
  const incidents = useData<Incident[]>("/incidents", coordinator);
  const [category, setCategory] = useState("all");
  const [search, setSearch] = useState("");
  const [accessible, setAccessible] = useState(false);
  const [pets, setPets] = useState(false);
  const [map, setMap] = useState(false);
  const [selected, setSelected] = useState<Resource | null>(null);
  const [capacity, setCapacity] = useState(0);
  const [occupancy, setOccupancy] = useState(0);
  const [published, setPublished] = useState(true);
  const [incidentId, setIncidentId] = useState("");
  const [resourceId, setResourceId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const action = useAction();
  const rows = (resources.data || []).filter(
    (resource) =>
      (category === "all" || resource.category === category) &&
      `${resource.name} ${resource.location}`
        .toLowerCase()
        .includes(search.toLowerCase()) &&
      (!accessible || resource.accessible) &&
      (!pets || resource.pet_friendly),
  );
  function open(resource: Resource) {
    setSelected(resource);
    setCapacity(resource.capacity);
    setOccupancy(resource.occupancy);
    setPublished(resource.published);
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) return;
    const result = await action.act(
      `/resources/${selected.id}`,
      { capacity, occupancy, published, version: selected.version },
      "PATCH",
      "Resource availability confirmed",
    );
    if (result) setSelected(null);
  }
  return (
    <>
      <PageHeading
        eyebrow={coordinator ? "RESOURCE COORDINATION" : "COMMUNITY RESOURCES"}
        title={
          coordinator
            ? "Capacity where it matters."
            : "Find help in your community"
        }
        subtitle="Configured community resources. Availability reflects the last coordinator confirmation."
      />
      {coordinator && (
        <div className="metrics three">
          <Metric
            label="Resource locations"
            value={resources.data?.length || 0}
            detail="Across the service area"
            icon={<Warehouse size={18} />}
          />
          <Metric
            label="Shelter availability"
            value={
              resources.data
                ?.filter((item) => item.category === "shelter")
                .reduce(
                  (total, item) => total + item.capacity - item.occupancy,
                  0,
                ) || 0
            }
            detail="Reported available places"
            icon={<Building2 size={18} />}
          />
          <Metric
            label="Pending assignments"
            value={
              requests.data?.filter((item) => item.status === "pending")
                .length || 0
            }
            detail="Require coordinator approval"
            tone="amber"
            icon={<Users size={18} />}
          />
        </div>
      )}
      <Panel
        title="Resource directory"
        action={
          <div className="segmented">
            <button
              aria-label="List view"
              className={!map ? "active" : ""}
              onClick={() => setMap(false)}
            >
              <List size={16} />
            </button>
            <button
              aria-label="Map view"
              className={map ? "active" : ""}
              onClick={() => setMap(true)}
            >
              <Map size={16} />
            </button>
          </div>
        }
      >
        <div className="filter-row">
          <div className="search">
            <Search size={16} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search resources or locations…"
              aria-label="Search resources"
            />
          </div>
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            aria-label="Resource category"
          >
            <option value="all">All resources</option>
            {["shelter", "food", "water", "medical", "transportation"].map(
              (value) => (
                <option key={value}>{value}</option>
              ),
            )}
          </select>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={accessible}
              onChange={(event) => setAccessible(event.target.checked)}
            />
            Accessible
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={pets}
              onChange={(event) => setPets(event.target.checked)}
            />
            Pet friendly
          </label>
        </div>
        {map ? (
          <IncidentMap
            items={rows}
            onSelect={(id) => {
              const resource = rows.find((item) => item.id === id);
              if (resource) open(resource);
            }}
          />
        ) : (
          <div className="resource-grid">
            {rows.map((resource) => (
              <ResourceCard key={resource.id} resource={resource}>
                {coordinator && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => open(resource)}
                  >
                    Update availability
                  </Button>
                )}
              </ResourceCard>
            ))}
          </div>
        )}
        {!rows.length && <Empty>No resources match these filters.</Empty>}
        {resources.error && <ErrorBox message={resources.error.message} />}
      </Panel>
      {action.feedback}
      {coordinator && (
        <Panel
          title="Agent review recommendations"
          eyebrow="ADVISORY · COORDINATOR APPROVAL REQUIRED"
        >
          <div className="request-list">
            {agentRuns.data
              ?.filter((run) => run.stage === "synthesis" && run.output)
              .slice(0, 3)
              .map((run) => (
                <article key={run.id}>
                  <p>{run.output?.summary}</p>
                  <ul>
                    {run.output?.recommended_actions?.map((recommendation) => (
                      <li key={recommendation}>{recommendation}</li>
                    ))}
                  </ul>
                  <small className="muted">
                    Source execution {run.id.slice(0, 8)} · Check confirmed
                    capacity before proposing an assignment.
                  </small>
                </article>
              ))}
            {!agentRuns.data?.some(
              (run) => run.stage === "synthesis" && run.output,
            ) && (
              <Empty>
                Recommendations appear after an actual synthesis execution
                completes.
              </Empty>
            )}
          </div>
        </Panel>
      )}
      {coordinator && (
        <div className="two-columns">
          <Panel title="Resource requests">
            <div className="request-list">
              {requests.data?.map((proposal) => (
                <article key={proposal.id}>
                  <div className="row">
                    <strong>
                      {
                        resources.data?.find(
                          (item) => item.id === proposal.resource_id,
                        )?.name
                      }
                    </strong>
                    <Badge value={proposal.status} />
                  </div>
                  <p>{proposal.rationale}</p>
                  <div className="row">
                    <small>{proposal.quantity} units requested</small>
                    {proposal.status === "pending" && (
                      <Button
                        size="sm"
                        disabled={action.busy}
                        onClick={() =>
                          action.act(
                            `/resource-requests/${proposal.id}/approve`,
                            {},
                            "POST",
                            "Assignment approved",
                          )
                        }
                      >
                        Approve assignment
                      </Button>
                    )}
                  </div>
                </article>
              ))}
            </div>
          </Panel>
          <Panel title="Propose an assignment">
            <form
              className="form"
              onSubmit={async (event) => {
                event.preventDefault();
                await action.act(
                  "/resource-requests",
                  {
                    incident_id: incidentId,
                    resource_id: resourceId,
                    quantity,
                    rationale:
                      "Coordinator proposed a capacity reservation after reviewing the directory.",
                  },
                  "POST",
                  "Assignment proposed; explicit approval is still required",
                );
              }}
            >
              <label>
                Incident
                <select
                  required
                  value={incidentId}
                  onChange={(event) => setIncidentId(event.target.value)}
                >
                  <option value="">Choose incident</option>
                  {incidents.data?.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Resource
                <select
                  required
                  value={resourceId}
                  onChange={(event) => setResourceId(event.target.value)}
                >
                  <option value="">Choose resource</option>
                  {resources.data?.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} · {item.capacity - item.occupancy} available
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Quantity
                <input
                  type="number"
                  min={1}
                  max={10000}
                  required
                  value={quantity}
                  onChange={(event) => setQuantity(Number(event.target.value))}
                />
              </label>
              <div className="callout">
                Capacity recommendations are advisory. This proposal does not
                reserve capacity until a coordinator approves it.
              </div>
              <Button disabled={action.busy}>Create pending proposal</Button>
            </form>
          </Panel>
        </div>
      )}
      <Drawer
        open={!!selected}
        onClose={() => setSelected(null)}
        title={
          coordinator ? "Confirm resource availability" : "Resource details"
        }
      >
        {selected &&
          (coordinator ? (
            <form className="form" onSubmit={save}>
              <h2>{selected.name}</h2>
              <label>
                Total capacity
                <input
                  type="number"
                  min={0}
                  required
                  value={capacity}
                  onChange={(event) => setCapacity(Number(event.target.value))}
                />
              </label>
              <label>
                Occupancy
                <input
                  type="number"
                  min={0}
                  max={capacity}
                  required
                  value={occupancy}
                  onChange={(event) => setOccupancy(Number(event.target.value))}
                />
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={published}
                  onChange={(event) => setPublished(event.target.checked)}
                />
                Publish in resident directory
              </label>
              <Button disabled={action.busy}>Confirm & save</Button>
              {action.feedback}
            </form>
          ) : (
            <ResourceCard resource={selected} />
          ))}
      </Drawer>
    </>
  );
}
