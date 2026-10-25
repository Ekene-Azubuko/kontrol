"use client";
import { useState } from "react";
import Image from "next/image";
import { vehicleSymbol, vehicleSymbolLabels } from "@/lib/vehicle-symbols";
import { Ambulance, Map, List } from "lucide-react";
import { useData } from "@/lib/api";
import type { Incident } from "@/lib/types";
import type { Dispatch, Hospital, Vehicle } from "@/lib/response-types";
import { IncidentMap, type MapItem } from "./map";
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

/** Show approved assignments and static resource locations. */
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
        subtitle="View approved assignments and resource locations."
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
      <div className="metrics response-metrics">
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

      </div>
      {view === "map" && (
        <Panel
          title="Live dispatched fleet"
          action={<span className="muted">Approved response markers</span>}
        >
          <IncidentMap
            items={networkMarkers(
              (incidents.data || []).filter((i) =>
                active.some((d) => d.incident_id === i.id),
              ),
              (hospitals.data || []).filter((h) => active.some((d) => d.hospital_id === h.id)),
              (vehicles.data || []).filter((v) => active.some((d) => d.vehicle_id === v.id)),
            )}
            fitToItems
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
                <Image className={`fleet-vehicle-icon vehicle-${vehicleSymbol(vehicle.vehicle_type)}`} src={`/icons/response/${vehicleSymbol(vehicle.vehicle_type)}.svg`} width={30} height={30} alt={vehicleSymbolLabels[vehicleSymbol(vehicle.vehicle_type)]} />
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
