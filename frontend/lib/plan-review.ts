import type { DiscoveredHospital, ResponsePlan } from "./response-types";

export type HospitalOrder = "nearest" | "farthest" | "recommended";
export type HospitalOption = {
  id: string;
  hospital: DiscoveredHospital;
  distanceMiles: number | null;
  distanceRank: number | null;
  recommendationRank: number | null;
};
export type ReviewCheck = { label: string; value: string; attention: boolean };

/** Measure straight-line distance from coordinates; never reuse an agent's prose as distance data. */
export function straightLineMiles(
  from: { latitude: number; longitude: number },
  to: { latitude: number; longitude: number },
): number | null {
  if (
    [from, to].some(
      (point) =>
        !Number.isFinite(point.latitude) ||
        !Number.isFinite(point.longitude) ||
        Math.abs(point.latitude) > 90 ||
        Math.abs(point.longitude) > 180,
    )
  )
    return null;
  const radians = (degrees: number) => (degrees * Math.PI) / 180;
  const deltaLat = radians(to.latitude - from.latitude);
  const deltaLon = radians(to.longitude - from.longitude);
  const arc =
    Math.sin(deltaLat / 2) ** 2 +
    Math.cos(radians(from.latitude)) *
      Math.cos(radians(to.latitude)) *
      Math.sin(deltaLon / 2) ** 2;
  return 3958.7613 * 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, arc))));
}

/** Keep distance ranks stable across display sorts and preserve the agent's explicit recommendation order. */
export function hospitalOptions(plan: ResponsePlan): HospitalOption[] {
  const rows = plan.runs
    .filter((run) => run.stage === "hospital")
    .flatMap((run) => {
      const recommendations = (run.output?.recommended_hospitals || []).map(
        (name) => name.trim().toLowerCase(),
      );
      return (run.output?.hospitals || []).map((hospital, index) => {
        const rank = recommendations.indexOf(
          hospital.name.trim().toLowerCase(),
        );
        return {
          id: `hospital:${run.id}:${index}`,
          hospital,
          distanceMiles: straightLineMiles(plan.incident, hospital),
          distanceRank: null,
          recommendationRank: rank === -1 ? null : rank + 1,
        } satisfies HospitalOption;
      });
    });
  return orderHospitals(rows, "nearest").map((row, index) => ({
    ...row,
    distanceRank: row.distanceMiles === null ? null : index + 1,
  }));
}

/** Sort a copy without changing agent output; unknown distances always remain at the end. */
export function orderHospitals(
  rows: HospitalOption[],
  order: HospitalOrder,
): HospitalOption[] {
  return [...rows].sort((a, b) => {
    if (order === "recommended") {
      const rank =
        (a.recommendationRank ?? Infinity) - (b.recommendationRank ?? Infinity);
      if (!Number.isNaN(rank) && rank !== 0) return rank;
    }
    if (a.distanceMiles === null)
      return b.distanceMiles === null ? a.id.localeCompare(b.id) : 1;
    if (b.distanceMiles === null) return -1;
    const distance =
      (a.distanceMiles - b.distanceMiles) * (order === "farthest" ? -1 : 1);
    return (
      distance ||
      a.hospital.name.localeCompare(b.hospital.name) ||
      a.id.localeCompare(b.id)
    );
  });
}

/** Remove only exact repeated notes, leaving their wording and all distinct limitations intact. */
export function uniqueNotes(notes: string[]): string[] {
  const seen = new Set<string>();
  return notes.filter((note) => {
    const key = note.trim().replace(/\s+/g, " ").toLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** Build four short review facts from structured records without summarizing or inventing agent claims. */
export function reviewChecks(
  plan: ResponsePlan,
  options: HospitalOption[],
): ReviewCheck[] {
  const unknownBeds = options.filter(
    (row) => row.hospital.available_beds == null,
  ).length;
  const noBeds =
    options.length > 0 &&
    options.every((row) => row.hospital.available_beds === 0);
  const automatic = plan.call?.detected_location?.status === "resolved";
  const patients = plan.requirements.estimated_patients;
  return [
    {
      label: "Incident location",
      value: automatic ? "Not human-verified" : "Check source record",
      attention: true,
    },
    {
      label: "Patient count",
      value:
        patients == null ? "Unknown" : `${patients} · unconfirmed estimate`,
      attention: patients == null,
    },
    {
      label: "Beds · agent snapshot",
      value: !options.length
        ? "No hospital options yet"
        : unknownBeds === options.length
          ? "Unknown at every option"
          : unknownBeds
            ? `Unknown at ${unknownBeds} of ${options.length} options`
            : noBeds
              ? "None reported available"
              : "Reported; rechecked on approval",
      attention: unknownBeds > 0 || noBeds,
    },
    {
      label: "Travel times",
      value: "Estimates, not live ETAs",
      attention: false,
    },
  ];
}

/** Keep explicit unmet requirements and known resource conflicts visible outside collapsed narrative notes. */
export function reviewAlerts(plan: ResponsePlan): string[] {
  const alerts = plan.runs.flatMap(
    (run) => run.output?.unfilled_requirements || [],
  );
  if (["awaiting_approval", "needs_information"].includes(plan.status)) {
    const destinations = new Map<
      string,
      { name: string; patients: number; available: number | null }
    >();
    for (const assignment of plan.assignments) {
      if (assignment.vehicle.status !== "available")
        alerts.push(`${assignment.vehicle.call_sign} is no longer available.`);
      if (assignment.hospital?.diversion)
        alerts.push(`${assignment.hospital.name} is on diversion.`);
      if (
        assignment.patients != null &&
        assignment.patients > assignment.vehicle.patient_capacity
      )
        alerts.push(
          `${assignment.vehicle.call_sign}: planned patients exceed recorded vehicle capacity.`,
        );
      const hospital = assignment.hospital;
      if (hospital && assignment.patients != null) {
        const available =
          hospital.available_beds ??
          (hospital.total_beds != null && hospital.occupied_beds != null
            ? Math.max(
                0,
                hospital.total_beds -
                  hospital.occupied_beds -
                  hospital.reserved_beds,
              )
            : null);
        const previous = destinations.get(hospital.id);
        destinations.set(hospital.id, {
          name: hospital.name,
          patients: (previous?.patients ?? 0) + assignment.patients,
          available,
        });
      }
    }
    for (const destination of destinations.values()) {
      if (
        destination.available !== null &&
        destination.patients > destination.available
      )
        alerts.push(
          `${destination.name}: planned patients exceed recorded available beds.`,
        );
    }
  }
  return uniqueNotes(alerts);
}
