"use client";
import { useState } from "react";
import { Ambulance, Building2, Map, List, Package } from "lucide-react";
import { useData } from "@/lib/api";
import type { Incident } from "@/lib/types";
import type { Dispatch, Hospital, Vehicle } from "@/lib/response-types";
import { IncidentMap, type MapItem, type MapRoute } from "./map";
import { PageHeading } from "./page-heading";
import { Badge, Empty, ErrorBox, Loading, Metric, Panel } from "./shared";
import { Button } from "./ui/button";
import { Drawer } from "./ui/dialog";
import { PlanDetail } from "./response-plans";

/** Build distinct, clickable incident, hospital and vehicle map layers. */
export function networkMarkers(
  incidents: Incident[],
  hospitals: Hospital[],
  vehicles: Vehicle[],
): MapItem[] {
  return [
    ...incidents.map((i) => ({ ...i, kind: "incident" as const })),
    ...hospitals.map((h) => ({
      ...h,
      id: `hospital:${h.id}`,
      category: "hospital",
      kind: "hospital" as const,
    })),
    ...vehicles.map((v) => ({
      ...v,
      id: `vehicle:${v.id}`,
      title: `${v.call_sign} · ${v.status.replaceAll("_", " ")}`,
      category: v.vehicle_type,
      kind: "vehicle" as const,
    })),
  ];
}

/** Draw response route points; these paths are not turn-by-turn directions. */
export function dispatchRoutes(dispatches: Dispatch[]): MapRoute[] {
  return dispatches
    .filter((d) => !d.released_at && d.status !== "cancelled")
    .map((d) => ({
      id: d.id,
      points: [
        [d.origin_longitude, d.origin_latitude],
        [d.incident.longitude, d.incident.latitude],
        ...(d.hospital
          ? [[d.hospital.longitude, d.hospital.latitude] as [number, number]]
          : []),
      ],
    }));
}

/** Show operational fleet availability and the lifecycle of approved responses. */
export function FleetWorkspace() {
  const vehicles = useData<Vehicle[]>("/vehicles");
  const dispatches = useData<Dispatch[]>("/dispatches");
  const hospitals = useData<Hospital[]>("/hospitals");
  const incidents = useData<Incident[]>("/incidents");
  const [view, setView] = useState("map");
  const [selected, setSelected] = useState<string | null>(null);
  const [plan, setPlan] = useState<string | null>(null);
  const selectedVehicle = vehicles.data?.find((v) => v.id === selected);
  const active =
    dispatches.data?.filter(
      (d) => !d.released_at && d.status !== "cancelled",
    ) || [];
  return (
    <>
      <PageHeading
        eyebrow="RESPONSE OPERATIONS"
        title="Fleet & Dispatch"
        subtitle="Track assignments from approval to arrival, transport and release."
        action={
          <div className="view-toggle">
            <Button
              variant={view === "map" ? "default" : "ghost"}
              onClick={() => setView("map")}
            >
              <Map size={16} />
              Map
            </Button>
            <Button
              variant={view === "list" ? "default" : "ghost"}
              onClick={() => setView("list")}
            >
              <List size={16} />
              List
            </Button>
          </div>
        }
      />
      <div className="metrics response-metrics three">
        <Metric
          label="Available units"
          value={
            vehicles.data?.filter((v) => v.status === "available").length || 0
          }
          detail="Ready for an approved plan"
          icon={<Ambulance size={18} />}
        />
        <Metric
          label="Active dispatches"
          value={active.length}
          detail="Assignments in progress"
          icon={<Map size={18} />}
        />
        <Metric
          label="Completed assignments"
          value={
            dispatches.data?.filter((d) => d.status === "completed").length || 0
          }
          detail="Recorded responses"
          icon={<List size={18} />}
        />
      </div>
      <div className="lifecycle">
        {[
          "available",
          "assigned",
          "en_route",
          "on_scene",
          "transporting",
          "completed",
          "available",
        ].map((status, index) => (
          <span key={`${status}-${index}`}>
            {index > 0 && <span className="muted">→ </span>}
            {status.replaceAll("_", " ")}
          </span>
        ))}
      </div>
      {view === "map" && (
        <Panel
          title="Live dispatched fleet"
          action={<span className="muted">Response routes</span>}
        >
          <IncidentMap
            items={networkMarkers(
              (incidents.data || []).filter((i) =>
                active.some((d) => d.incident_id === i.id),
              ),
              hospitals.data || [],
              vehicles.data || [],
            )}
            routes={dispatchRoutes(dispatches.data || [])}
            onSelect={(id) => {
              if (id.startsWith("vehicle:")) setSelected(id.slice(8));
            }}
          />
        </Panel>
      )}
      {vehicles.error && <ErrorBox message={vehicles.error.message} />}
      {vehicles.isLoading && <Loading />}
      <Panel title="Emergency fleet">
        <div className="vehicle-grid">
          {vehicles.data?.map((vehicle) => (
            <button
              className={`vehicle-card ${vehicle.status}`}
              onClick={() => setSelected(vehicle.id)}
              key={vehicle.id}
            >
              <div className="row">
                <Ambulance size={22} />
                <Badge value={vehicle.status} />
              </div>
              <h3>{vehicle.call_sign}</h3>
              <p>{vehicle.vehicle_type.replaceAll("_", " ")}</p>
              <div className="resource-tags">
                {vehicle.capabilities.map((cap) => (
                  <span key={cap}>{cap.replaceAll("_", " ")}</span>
                ))}
              </div>
              <small>{vehicle.location}</small>
              {vehicle.assignment && (
                <progress value={vehicle.assignment.progress} max={1} />
              )}
            </button>
          ))}
        </div>
      </Panel>
      <Panel title="Active assignments">
        {active.map((dispatch) => (
          <div className="dispatch-row" key={dispatch.id}>
            <div>
              <strong>{dispatch.vehicle.call_sign}</strong>
              <p>
                {dispatch.incident.location} →{" "}
                {dispatch.hospital?.name || "On-scene support"}
              </p>
            </div>
            <Badge value={dispatch.status} />
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setPlan(dispatch.plan_id)}
            >
              View plan
            </Button>
          </div>
        ))}
        {!active.length && (
          <Empty>Approve a response plan to start dispatch.</Empty>
        )}
      </Panel>
      <Drawer
        open={!!selectedVehicle}
        title="Vehicle details"
        onClose={() => setSelected(null)}
      >
        {selectedVehicle && (
          <div className="detail-section">
            <h1>{selectedVehicle.call_sign}</h1>
            <Badge value={selectedVehicle.status} />
            <p>
              {selectedVehicle.vehicle_type.replaceAll("_", " ")} ·{" "}
              {selectedVehicle.patient_capacity} patient capacity
            </p>
            <h3>Capabilities</h3>
            <div className="resource-tags">
              {selectedVehicle.capabilities.map((c) => (
                <span key={c}>{c.replaceAll("_", " ")}</span>
              ))}
            </div>
            <h3>Current location</h3>
            <p>{selectedVehicle.location}</p>
            <p className="mono">
              {selectedVehicle.latitude.toFixed(5)},{" "}
              {selectedVehicle.longitude.toFixed(5)}
            </p>
            {selectedVehicle.assignment ? (
              <>
                <h3>Current assignment</h3>
                <Badge value={selectedVehicle.assignment.status} />
                <progress value={selectedVehicle.assignment.progress} max={1} />
                <Button
                  onClick={() => {
                    setPlan(selectedVehicle.assignment!.plan_id);
                    setSelected(null);
                  }}
                >
                  View approved plan
                </Button>
              </>
            ) : (
              <p className="muted">
                No active assignment. Available for dispatcher-approved
                responses.
              </p>
            )}
          </div>
        )}
      </Drawer>
      <PlanDetail id={plan} onClose={() => setPlan(null)} />
    </>
  );
}

/** Inspect synthetic hospital capacity, capabilities and simple medicine/equipment inventory. */
export function HospitalWorkspace() {
  const incidents = useData<Incident[]>("/incidents");
  const [incident, setIncident] = useState("");
  const hospitals = useData<Hospital[]>(
    `/hospitals${incident ? `?incident_id=${incident}` : ""}`,
  );
  const [selected, setSelected] = useState<string | null>(null);
  const hospital = hospitals.data?.find((h) => h.id === selected);
  return (
    <>
      <PageHeading
        eyebrow="DISCOVERED & CONFIGURED FACILITIES"
        title="Hospital Network"
        subtitle="Review available beds, reserved capacity and resources across the hospital network."
        action={
          <label className="incident-picker">
            Travel estimates from
            <select
              aria-label="Selected incident for travel estimates"
              value={incident}
              onChange={(e) => setIncident(e.target.value)}
            >
              <option value="">Select an incident</option>
              {incidents.data?.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.title}
                </option>
              ))}
            </select>
          </label>
        }
      />
      <div className="metrics response-metrics three">
        <Metric
          label="Available beds"
          value={
            hospitals.data
              ?.filter((h) => !h.diversion)
              .reduce((sum, h) => sum + (h.available_beds || 0), 0) || 0
          }
          detail="Excludes diverted facilities"
          icon={<Building2 size={18} />}
        />
        <Metric
          label="Reserved for arrivals"
          value={
            hospitals.data?.reduce((sum, h) => sum + h.reserved_beds, 0) || 0
          }
          detail="Approved transports only"
          icon={<Ambulance size={18} />}
        />
        <Metric
          label="Low-stock items"
          value={
            hospitals.data
              ?.flatMap((h) => h.inventory)
              .filter((i) => i.quantity <= i.low_stock_threshold).length || 0
          }
          detail="Configured inventory indicators"
          icon={<Package size={18} />}
        />
      </div>
      {hospitals.error && <ErrorBox message={hospitals.error.message} />}
      {hospitals.isLoading && <Loading />}
      <div className="hospital-grid">
        {hospitals.data?.map((h) => (
          <article className="hospital-card" key={h.id}>
            <div className="row">
              <span className="hospital-icon">
                <Building2 size={24} />
              </span>
              <Badge value={h.diversion ? "diversion" : "accepting"} />
            </div>
            <h2>
              <button
                className="hospital-name"
                onClick={() => setSelected(h.id)}
              >
                {h.name}
              </button>
            </h2>
            <p>{h.location}</p>
            <div className="hospital-capacity">
              <strong className={h.available_beds === null ? "capacity-unknown" : undefined}>
                {h.available_beds ?? "Unknown"}
              </strong>
              <span>available / {h.total_beds ?? "unknown"} total beds</span>
            </div>
            <div className="bed-bar">
              <span
                className="occupied"
                style={{
                  width: `${h.total_beds ? ((h.occupied_beds || 0) / h.total_beds) * 100 : 0}%`,
                }}
              />
              <span
                className="reserved"
                style={{
                  width: `${h.total_beds ? (h.reserved_beds / h.total_beds) * 100 : 0}%`,
                }}
              />
            </div>
            <div className="row muted">
              <small>{h.occupied_beds ?? "Unknown"} occupied</small>
              <small>{h.reserved_beds} reserved</small>
            </div>
            <details className="hospital-capabilities">
              <summary>Capabilities ({h.capabilities.length})</summary>
              <ul>
                {h.capabilities.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </details>
            {!!h.source_urls.length && (
              <div className="hospital-sources">
                {h.source_urls.map((url, index) => (
                  <a key={url} href={url} target="_blank" rel="noreferrer">
                    Source {index + 1}
                  </a>
                ))}
              </div>
            )}
            <div className="row hospital-card-footer">
              <small>
                {h.travel_minutes === null
                  ? "Select an incident for travel time"
                  : `${h.travel_minutes} min illustrative travel`}
              </small>
              <button className="text-link" onClick={() => setSelected(h.id)}>
                View inventory →
              </button>
            </div>
          </article>
        ))}
      </div>
      <Drawer
        open={!!hospital}
        onClose={() => setSelected(null)}
        title="Hospital details"
      >
        {hospital && (
          <div className="detail-section">
            <h1>{hospital.name}</h1>
            <p>{hospital.location}</p>
            <Badge value={hospital.diversion ? "diversion" : "accepting"} />
            <h2>{hospital.available_beds ?? "Unknown"} available beds</h2>
            <p>
              {hospital.occupied_beds ?? "Unknown"} occupied ·{" "}
              {hospital.reserved_beds} reserved ·{" "}
              {hospital.total_beds ?? "Unknown"} total
            </p>
            <div className="resource-tags">
              {hospital.capabilities.map((c) => (
                <span key={c}>{c}</span>
              ))}
            </div>
            <h3>Medicine & equipment</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Quantity</th>
                    <th>Stock</th>
                  </tr>
                </thead>
                <tbody>
                  {hospital.inventory.map((item) => (
                    <tr key={item.id}>
                      <td>
                        {item.name}
                        <small>{item.category}</small>
                      </td>
                      <td>{item.quantity}</td>
                      <td>
                        <Badge
                          value={
                            item.quantity <= item.low_stock_threshold
                              ? "low_stock"
                              : "available"
                          }
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Drawer>
    </>
  );
}
