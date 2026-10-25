"use client";
import { useState } from "react";
import type { ResponsePlan } from "@/lib/response-types";
import {
  hospitalOptions,
  orderHospitals,
  type HospitalOrder,
} from "@/lib/plan-review";
import { IncidentMap, type MapItem } from "./map";

/** Compare hospital proximity without changing the agent's recommendations or proposed destinations. */
export function PlanHospitals({ plan }: { plan: ResponsePlan }) {
  const [order, setOrder] = useState<HospitalOrder>("nearest");
  const [selected, setSelected] = useState<string | null>(null);
  const options = hospitalOptions(plan);
  const hospitalRuns = plan.runs.filter(
    (run) => run.stage === "hospital" && run.output,
  );
  const facilities = plan.runs.flatMap((run) =>
    (run.output?.discovered_facilities || []).map((facility, index) => ({
      ...facility,
      id: `facility:${run.id}:${index}`,
    })),
  );
  if (!options.length && !facilities.length && !hospitalRuns.length)
    return null;
  const sorted = orderHospitals(options, order);
  const markers: MapItem[] = [
    {
      ...plan.incident,
      id: "incident",
      title: `Incident: ${plan.incident.location}`,
      kind: "incident",
    },
    ...options
      .filter((row) => row.distanceMiles !== null)
      .map((row) => ({
        id: row.id,
        latitude: row.hospital.latitude,
        longitude: row.hospital.longitude,
        title: `${row.distanceRank}. ${row.hospital.name} · ${row.distanceMiles!.toFixed(1)} mi straight-line`,
        category: "hospital",
        kind: "hospital" as const,
        markerLabel: String(row.distanceRank),
        nearest: row.distanceRank === 1,
      })),
    ...facilities
      .filter(
        (facility) => facility.latitude !== null && facility.longitude !== null,
      )
      .map((facility) => ({
        id: facility.id,
        latitude: facility.latitude!,
        longitude: facility.longitude!,
        title: facility.name,
        category: facility.facility_type,
        kind: "facility" as const,
        markerLabel: "F",
      })),
  ];
  return (
    <section
      className="plan-hospitals"
      aria-label="Hospital distance comparison"
    >
      <div className="hospital-comparison-heading">
        <h3>
          Hospital options <span className="count">{options.length}</span>
        </h3>
        <label>
          Sort hospitals
          <select
            aria-label="Sort hospitals"
            value={order}
            disabled={!options.length}
            onChange={(event) => setOrder(event.target.value as HospitalOrder)}
          >
            <option value="nearest">Nearest first</option>
            <option value="farthest">Farthest first</option>
            <option value="recommended">Agent recommendation</option>
          </select>
        </label>
      </div>
      {markers.length > 1 && (
        <IncidentMap
          items={markers}
          onSelect={setSelected}
          selectedId={selected}
          fitToItems
          caption="HOSPITAL OPTIONS"
          showLegend={false}
        />
      )}
      {!!options.length && (
        <p className="hospital-distance-key">
          <strong>1 = closest to incident</strong> · Higher numbers are farther
          away. Straight-line distance, not suitability.
          {!!facilities.length && " F = other response facility."}
        </p>
      )}
      {!options.length && (
        <p className="muted">No hospital options returned.</p>
      )}
      <ol className="hospital-comparison-list">
        {sorted.map((row) => {
          const hospital = row.hospital;
          const method =
            hospital.travel_time_method === "road_routing"
              ? "road estimate"
              : hospital.travel_time_method === "coordinate_estimate"
                ? "distance estimate"
                : "method unavailable";
          return (
            <li
              key={row.id}
              className={selected === row.id ? "selected" : ""}
              data-distance-rank={row.distanceRank}
            >
              <button
                className="hospital-option-select"
                aria-pressed={selected === row.id}
                aria-label={`Highlight ${hospital.name} on map`}
                onClick={() => setSelected(row.id)}
              >
                <span
                  className={`hospital-distance-rank ${row.distanceRank === 1 ? "nearest" : ""}`}
                >
                  {row.distanceRank ?? "?"}
                </span>
                <strong>{hospital.name}</strong>
                <span className="hospital-distance">
                  {row.distanceMiles === null
                    ? "Distance unknown"
                    : `${row.distanceMiles.toFixed(1)} mi`}
                  <small>straight-line</small>
                </span>
              </button>
              <div className="hospital-option-facts">
                <span>
                  {row.recommendationRank
                    ? `Agent choice #${row.recommendationRank}`
                    : "Other evaluated option"}
                </span>
                <span>
                  {hospital.estimated_travel_minutes == null
                    ? "Travel time unknown"
                    : `${hospital.estimated_travel_minutes} min · ${method}`}
                </span>
                <span>
                  {hospital.available_beds == null
                    ? "Beds unknown"
                    : `${hospital.available_beds} beds reported`}
                </span>
                <span>
                  {hospital.diversion_status == null
                    ? "Diversion unknown"
                    : hospital.diversion_status === true
                      ? "On diversion"
                      : hospital.diversion_status === false
                        ? "No diversion reported"
                        : hospital.diversion_status}
                </span>
              </div>
              <details className="hospital-option-details">
                <summary>Details & sources</summary>
                <p>{hospital.address}</p>
                <p>{hospital.suitability_notes}</p>
                {!!hospital.documented_capabilities.length && (
                  <p>
                    Documented capabilities:{" "}
                    {hospital.documented_capabilities
                      .join(", ")
                      .replaceAll("_", " ")}
                  </p>
                )}
                <div className="hospital-source-links">
                  {hospital.source_urls.map((url, index) => (
                    <a key={url} href={url} target="_blank" rel="noreferrer">
                      Source {index + 1}
                    </a>
                  ))}
                </div>
              </details>
            </li>
          );
        })}
      </ol>
      {!!facilities.length && (
        <details className="agent-reasoning">
          <summary>Other response facilities ({facilities.length})</summary>
          <ul>
            {facilities.map((facility) => (
              <li key={facility.id}>
                {facility.name} · {facility.address}
              </li>
            ))}
          </ul>
        </details>
      )}
      {hospitalRuns.map((run) => (
        <details className="agent-reasoning" key={run.id}>
          <summary>Full hospital reasoning</summary>
          <p>{run.output?.reasoning}</p>
          {!!run.output?.limitations?.length && (
            <ul>
              {run.output.limitations.map((note, index) => (
                <li key={index}>{note}</li>
              ))}
            </ul>
          )}
        </details>
      ))}
    </section>
  );
}
