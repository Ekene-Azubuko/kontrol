import { test, expect } from "@playwright/test";
import {
  hospitalOptions,
  orderHospitals,
  reviewChecks,
  reviewAlerts,
  straightLineMiles,
  uniqueNotes,
} from "../lib/plan-review";
import { reviewFixture } from "./plan-review-fixture";

test("geographic proximity and agent recommendation remain independent", () => {
  const plan = reviewFixture();
  const original = structuredClone(plan);
  const options = hospitalOptions(plan);
  expect(options.map((row) => row.hospital.name)).toEqual([
    "SIM · Near Hospital",
    "SIM · Middle Hospital",
    "SIM · Far Hospital",
  ]);
  expect(options.map((row) => row.distanceRank)).toEqual([1, 2, 3]);
  expect(
    orderHospitals(options, "farthest").map((row) => row.distanceRank),
  ).toEqual([3, 2, 1]);
  expect(
    orderHospitals(options, "recommended").map((row) => row.distanceRank),
  ).toEqual([3, 2, 1]);
  expect(options[0].recommendationRank).toBeNull();
  expect(options[2].recommendationRank).toBe(1);
  expect(plan).toEqual(original);
});

test("unavailable coordinates sort last and cannot masquerade as the closest hospital", () => {
  const plan = reviewFixture();
  plan.runs[0].output!.hospitals![0].latitude = NaN;
  const options = hospitalOptions(plan);
  for (const order of ["nearest", "farthest"] as const) {
    const last = orderHospitals(options, order).at(-1)!;
    expect(last.hospital.name).toBe("SIM · Far Hospital");
    expect(last.distanceMiles).toBeNull();
    expect(last.distanceRank).toBeNull();
  }
  expect(
    straightLineMiles(
      { latitude: 0, longitude: 0 },
      { latitude: 1, longitude: 0 },
    ),
  ).toBeCloseTo(69.09, 1);
  expect(
    straightLineMiles(
      { latitude: 0, longitude: 0 },
      { latitude: 0, longitude: 0 },
    ),
  ).toBe(0);
  expect(
    straightLineMiles(
      { latitude: 91, longitude: 0 },
      { latitude: 0, longitude: 0 },
    ),
  ).toBeNull();
});

test("unknown counts and capacity remain distinct from reported zero", () => {
  const plan = reviewFixture();
  let checks = reviewChecks(plan, hospitalOptions(plan));
  expect(checks.find((row) => row.label === "Patient count")?.value).toBe(
    "Unknown",
  );
  expect(checks.find((row) => row.label.startsWith("Beds"))?.value).toBe(
    "Unknown at every option",
  );
  plan.requirements.estimated_patients = 0;
  plan.runs[0].output!.hospitals!.forEach((hospital) => {
    hospital.available_beds = 0;
  });
  checks = reviewChecks(plan, hospitalOptions(plan));
  expect(checks.find((row) => row.label === "Patient count")?.value).toBe(
    "0 · unconfirmed estimate",
  );
  expect(checks.find((row) => row.label.startsWith("Beds"))?.value).toBe(
    "None reported available",
  );
});

test("distinct constraints and explicit unmet requirements are preserved", () => {
  expect(
    uniqueNotes([
      "Route is closed.",
      " Route  is closed. ",
      "A second route is also closed.",
    ]),
  ).toEqual(["Route is closed.", "A second route is also closed."]);
  const plan = reviewFixture();
  expect(uniqueNotes(plan.constraints)).toHaveLength(23);
  expect(reviewAlerts(plan)).toEqual([
    "No accessible rescue unit was supplied.",
  ]);
});

test("known resource conflicts remain visible before approval without treating unknown capacity as zero", () => {
  const plan = reviewFixture();
  plan.runs[1].output!.unfilled_requirements = [];
  plan.assignments = [
    {
      id: "assignment",
      vehicle_id: "unit",
      hospital_id: "hospital",
      patients: 2,
      reason: "Fictional proposal",
      vehicle_eta_minutes: 5,
      hospital_eta_minutes: 5,
      vehicle_eta_method: "coordinate_estimate",
      hospital_eta_method: "coordinate_estimate",
      response_role: "ambulance",
      vehicle: {
        id: "unit",
        call_sign: "SIM 1",
        vehicle_type: "ambulance",
        capabilities: [],
        patient_capacity: 1,
        status: "available",
        latitude: 37.78,
        longitude: -122.42,
        location: "Exercise",
        travel_minutes: 5,
      },
      hospital: {
        id: "hospital",
        name: "SIM Hospital",
        location: "Exercise",
        latitude: 37.78,
        longitude: -122.42,
        capabilities: [],
        total_beds: null,
        occupied_beds: null,
        reserved_beds: 0,
        available_beds: null,
        diversion: false,
        travel_minutes: 5,
        inventory: [],
        source_urls: [],
        discovered_by_agent: false,
      },
    },
  ];
  expect(reviewAlerts(plan)).toEqual([
    "SIM 1: planned patients exceed recorded vehicle capacity.",
  ]);
  plan.assignments[0].hospital!.available_beds = 1;
  expect(reviewAlerts(plan)).toContain(
    "SIM Hospital: planned patients exceed recorded available beds.",
  );
  plan.assignments[0].vehicle.status = "assigned";
  expect(reviewAlerts(plan)).toContain("SIM 1 is no longer available.");
  plan.status = "approved";
  expect(reviewAlerts(plan)).toEqual([]);
});
