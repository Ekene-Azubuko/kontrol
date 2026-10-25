import { test, expect } from "@playwright/test";
import type { Incident } from "../lib/types";
import type { ResponsePlan } from "../lib/response-types";

const incident: Incident = {
  id: "navigation-incident",
  title: "SIMULATION · Navigation review",
  category: "collision",
  severity: "moderate",
  status: "unverified",
  latitude: 37.78,
  longitude: -122.42,
  location: "Fictional exercise location",
  summary: "Fictional incident for navigation testing.",
  version: 1,
  created_at: "2026-01-01T12:00:00Z",
  assigned_to: null,
  reported_casualties: null,
  response_status: "awaiting_approval",
};
const plan: ResponsePlan = {
  id: "navigation-plan",
  incident_id: incident.id,
  incident,
  report_source: "simulation",
  call: null,
  status: "awaiting_approval",
  revision: 1,
  revision_note: "",
  summary: "SIMULATION / NOT FOR EMERGENCY USE",
  requirements: {},
  constraints: [],
  feasible: false,
  version: 1,
  created_at: incident.created_at,
  approved_at: null,
  completed_at: null,
  decision_note: null,
  assignments: [],
  runs: [],
  dispatches: [],
};

for (const route of ["overview", "incidents"]) {
  // New reviewable plans must refresh the page without stealing focus in a drawer.
  test(`${route} opens plan review only after selection`, async ({ page }) => {
    let plans = [plan];
    let listReads = 0;
    await page.route("**/api/**", async (request) => {
      const path = new URL(request.request().url()).pathname;
      expect(request.request().method()).toBe("GET");
      if (path === "/api/events") {
        await request.fulfill({
          contentType: "text/event-stream",
          body: 'data: {"type":"refresh"}\n\n',
        });
      } else if (path === "/api/response-plans") {
        listReads += 1;
        await request.fulfill({ json: plans });
      } else if (path === `/api/response-plans/${plan.id}`) {
        await request.fulfill({ json: plan });
      } else if (path === "/api/incidents") {
        await request.fulfill({ json: [incident] });
      } else if (path === `/api/incidents/${incident.id}`) {
        await request.fulfill({
          json: {
            ...incident,
            reports: [],
            findings: [],
            evidence: [],
            history: [],
          },
        });
      } else {
        await request.fulfill({ json: [] });
      }
    });
    await page.goto(`/coordinator/${route}`);
    await expect(page.locator(".table-title").first()).toBeVisible();
    // Wait for a second list read to cover both initial load and an SSE refresh.
    await expect.poll(() => listReads, { timeout: 12000 }).toBeGreaterThan(1);
    await expect(page.getByRole("dialog")).toHaveCount(0);

    if (route === "incidents") {
      await page
        .getByRole("button", { name: "View response", exact: true })
        .click();
      await expect(
        page.getByRole("dialog", { name: "Incident response" }),
      ).toBeVisible();
      await expect(
        page.getByRole("dialog", { name: "Response plan review" }),
      ).toHaveCount(0);
    }
    await page.locator(".plan-card").first().click();
    const review = page.getByRole("dialog", { name: "Response plan review" });
    await expect(review).toBeVisible();
    await review.getByRole("button", { name: "Close details" }).click();
    if (route === "incidents") {
      await page
        .getByRole("dialog", { name: "Incident response" })
        .getByRole("button", { name: "Close details" })
        .click();
    }

    const previousReads = listReads;
    plans = [
      ...plans,
      { ...plan, id: "new-pending-plan", status: "needs_information" },
    ];
    await expect
      .poll(() => listReads, { timeout: 12000 })
      .toBeGreaterThan(previousReads);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page
      .getByRole("link", { name: "Recorded Calls", exact: true })
      .click();
    await page
      .getByRole("link", {
        name: route === "overview" ? "Command Center" : "Incidents",
        exact: true,
      })
      .click();
    await expect(page.locator(".table-title").first()).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
}
