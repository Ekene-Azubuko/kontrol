import { test, expect } from "@playwright/test";

const incidents = ["Collision response", "Fire response"].map((title, i) => ({
  id: `incident-${i}`, title, category: i ? "fire" : "collision", severity: "moderate",
  status: "needs_review", latitude: 37.7787 + i * 0.01, longitude: -122.4148,
  location: `Prepared location ${i}`, reported_casualties: 1, response_status: "assigned",
}));
const hospitals = incidents.map((_, i) => ({
  id: `hospital-${i}`, name: `Prepared destination ${i}`, location: `Destination address ${i}`,
  latitude: 37.7568 + i * 0.01, longitude: -122.4052, capabilities: [], source_urls: [],
}));
const fleet = ["ambulance", "police", "fire_engine", "ambulance", "rescue_unit"].map((vehicle_type, i) => ({
  id: `vehicle-${i}`, call_sign: ["AMB-01", "POL-01", "FIR-01", "AMB-02", "RES-01"][i],
  vehicle_type, capabilities: [], patient_capacity: vehicle_type === "ambulance" ? 2 : 0,
  status: "assigned", latitude: 37.77 + i * 0.003, longitude: -122.42 + i * 0.004,
  location: "Prepared vehicle location",
}));
const plans = incidents.map((incident, i) => ({
  id: `plan-${i}`, incident_id: incident.id, incident, status: "approved", revision: 1,
  summary: "Prepared approved response", requirements: {}, constraints: [], assignments: [], runs: [], dispatches: [],
}));
const dispatches = fleet.map((vehicle, i) => {
  const response = i < 2 ? 0 : 1;
  return {
    id: `dispatch-${i}`, plan_id: plans[response].id, incident_id: incidents[response].id,
    vehicle_id: vehicle.id, hospital_id: vehicle.vehicle_type === "ambulance" ? hospitals[response].id : null,
    status: "assigned", released_at: null, vehicle, incident: incidents[response],
    hospital: vehicle.vehicle_type === "ambulance" ? hospitals[response] : null,
  };
});

/** Check that each response keeps its vehicle symbols and hospital when the map is filtered. */
test("approved response maps distinguish vehicles and show matching hospital destinations", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/events") {
      await route.fulfill({ contentType: "text/event-stream", body: 'data: {"type":"refresh"}\n\n' });
      return;
    }
    const records: Record<string, unknown> = {
      "/api/incidents": incidents, "/api/response-plans": plans, "/api/hospitals": hospitals,
      "/api/vehicles": fleet, "/api/dispatches": dispatches,
    };
    await route.fulfill({ json: records[path] || [] });
  });
  await page.goto("/coordinator/overview");
  await expect(page.locator(".startup-screen")).toHaveCount(0);
  const map = page.locator(".map-wrap");
  await expect(map).toHaveAttribute("data-ready", "true", { timeout: 20000 });
  await expect(map.locator(".map-marker.vehicle")).toHaveCount(5);
  await expect(map.locator(".map-marker.hospital")).toHaveCount(2);
  for (const [symbol, count] of [["ambulance", 2], ["police", 1], ["fire", 1], ["rescue", 1]] as const) {
    const icons = map.locator(`[data-vehicle-type="${symbol}"] img`);
    await expect(icons).toHaveCount(count);
    await expect(icons.first()).toHaveAttribute("src", `/icons/response/${symbol}.svg`);
  }
  const filter = page.getByRole("combobox", { name: "Filter map by response" });
  await filter.selectOption("plan-0");
  await expect(map.locator(".map-marker.vehicle")).toHaveCount(2);
  await expect(map.locator(".map-marker.hospital")).toHaveCount(1);
  await expect(map.getByRole("button", { name: "Prepared destination 0", exact: true })).toBeVisible();
  await expect(map.locator('[data-vehicle-type="fire"]')).toHaveCount(0);
  await filter.selectOption("plan-1");
  await expect(map.locator(".map-marker.vehicle")).toHaveCount(3);
  await expect(map.getByRole("button", { name: "Prepared destination 1", exact: true })).toBeVisible();
  await expect(map.locator('[data-vehicle-type="fire"]')).toBeVisible();
  await expect(map.locator('[data-vehicle-type="police"]')).toHaveCount(0);
  await filter.selectOption("all");
  await expect(map.locator(".map-marker.vehicle")).toHaveCount(5);
  // Destination markers must remain above the legend, including the southernmost hospital.
  const legend = await map.locator(".map-legend").boundingBox();
  for (const marker of await map.locator(".map-marker.hospital").all()) {
    await expect.poll(async () => {
      const bounds = await marker.boundingBox();
      return bounds ? bounds.y + bounds.height < legend!.y : false;
    }).toBe(true);
  }
  await map.screenshot({ path: "test-results/response-vehicle-icons.png" });
  await page.goto("/coordinator/dispatch");
  await expect(page.locator('.map-marker.hospital')).toHaveCount(2);
  await expect(page.locator('.fleet-vehicle-icon[alt="Police car"]')).toHaveCount(1);
  await expect(page.locator('.fleet-vehicle-icon[alt="Fire truck"]')).toHaveCount(1);
});
