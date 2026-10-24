import { test, expect } from "@playwright/test";
import type { ResponsePlan, Hospital, Vehicle } from "../lib/response-types";
const coordinatorHeaders = { Authorization: "Bearer demo-coordinator" };
const residentHeaders = { Authorization: "Bearer demo-resident" };

/** Follow a resident submission through agent execution and human approval. */
test("resident report → four agents → approved dispatch → hospital arrival → completion", async ({
  page,
  request,
}) => {
  test.setTimeout(180000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/resident/report");
  const unique = Date.now();
  const description = `Browser test ${unique}: Two vehicles collided. Two injured people reported.`;
  const location = `Market Street browser test ${unique}`;
  await page.getByRole("button", { name: "collision", exact: true }).click();
  await page
    .getByPlaceholder("Describe what you observed and where")
    .fill(description);
  await page.getByLabel("Reported injured people (if known)").fill("2");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Incident location", { exact: true }).fill(location);
  await page.getByRole("button", { name: "Continue" }).click();
  const submitted = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/reports") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Submit report", exact: true })
    .click();
  const report = await (await submitted).json();
  await expect(
    page.getByText("Your observation is in the queue."),
  ).toBeVisible();
  await page.goto("/coordinator/overview");
  await expect(page.locator(".map-wrap[data-ready=true]")).toBeVisible({
    timeout: 30000,
  });
  await expect(
    page.getByRole("button", {
      name: `Collision observation · ${location}`,
      exact: true,
    }),
  ).toBeVisible();
  await page.goto("/coordinator/agents");
  await expect(
    page.getByRole("heading", { name: "Hospital Agent", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Dispatch Agent", exact: true }),
  ).toBeVisible();
  let plan: ResponsePlan | undefined;
  await expect
    .poll(
      async () => {
        const plans: ResponsePlan[] = await (
          await request.get("/api/response-plans", {
            headers: coordinatorHeaders,
          })
        ).json();
        plan = plans.find((item) =>
          item.runs.some((run) => run.report_id === report.id),
        );
        return plan?.status;
      },
      { timeout: 45000 },
    )
    .toBe("awaiting_approval");
  const reviewed = plan!;
  expect(reviewed.runs.map((run) => run.stage).sort()).toEqual([
    "dispatch",
    "hospital",
    "intake",
    "planning",
  ]);
  const hospitalRun = reviewed.runs.find((run) => run.stage === "hospital")!;
  const dispatchRun = reviewed.runs.find((run) => run.stage === "dispatch")!;
  expect(
    Math.max(
      Date.parse(hospitalRun.started_at!),
      Date.parse(dispatchRun.started_at!),
    ),
  ).toBeLessThan(
    Math.min(
      Date.parse(hospitalRun.completed_at!),
      Date.parse(dispatchRun.completed_at!),
    ),
  );
  const baseline: Hospital[] = await (
    await request.get("/api/hospitals", { headers: coordinatorHeaders })
  ).json();
  await page.goto("/coordinator/response-plans");
  await page.getByLabel("Search response plans").fill(location);
  await page.locator(".plan-card").filter({ hasText: location }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "Proposed assignments", exact: true }),
  ).toBeVisible();
  await dialog
    .locator("summary")
    .filter({ hasText: "Hospital options evaluated" })
    .click();
  await expect(
    dialog
      .getByText("beds available in evaluation snapshot", { exact: false })
      .first(),
  ).toBeVisible();
  await dialog
    .getByLabel("Decision or revision note")
    .fill(
      "Reviewed supplied capacity, vehicle capabilities, patient estimate and alternatives.",
    );
  await page.screenshot({
    path: "test-results/response-plan-review.png",
    fullPage: true,
  });
  await dialog
    .getByRole("button", { name: "Approve plan", exact: true })
    .click();
  await expect(
    dialog.getByText("Plan approved. Dispatch has started."),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "Close details" }).click();
  await page.goto("/coordinator/communications");
  await expect(
    page.locator(".operational-message").filter({ hasText: location }).first(),
  ).toBeVisible();
  await page.goto("/coordinator/dispatch");
  await expect(page.locator(".map-wrap[data-ready=true]")).toBeVisible({
    timeout: 30000,
  });
  const transport = reviewed.assignments.find(
    (assignment) => assignment.hospital_id,
  )!;
  const movingMarker = page.locator(
    `.map-marker.vehicle[aria-label^="${transport.vehicle.call_sign}"]`,
  );
  await expect(movingMarker).toHaveAttribute("aria-label", /en route/, {
    timeout: 30000,
  });
  const originalPosition = await movingMarker.getAttribute("style");
  await expect
    .poll(() => movingMarker.getAttribute("style"), { timeout: 8000 })
    .not.toBe(originalPosition);
  await page.screenshot({
    path: "test-results/fleet-in-motion.png",
    fullPage: true,
  });
  await expect
    .poll(
      async () =>
        (
          await (
            await request.get(`/api/response-plans/${reviewed.id}`, {
              headers: coordinatorHeaders,
            })
          ).json()
        ).status,
      { timeout: 90000, intervals: [2000] },
    )
    .toBe("completed");
  const after: Hospital[] = await (
    await request.get("/api/hospitals", { headers: coordinatorHeaders })
  ).json();
  expect(after.reduce((sum, h) => sum + (h.occupied_beds || 0), 0)).toBe(
    baseline.reduce((sum, h) => sum + (h.occupied_beds || 0), 0) + 2,
  );
  expect(after.reduce((sum, h) => sum + h.reserved_beds, 0)).toBe(0);
  const vehicles: Vehicle[] = await (
    await request.get("/api/vehicles", { headers: coordinatorHeaders })
  ).json();
  expect(vehicles.every((vehicle) => vehicle.status === "available")).toBe(
    true,
  );
  await page.goto("/coordinator/hospitals");
  await expect(page.locator(".hospital-card")).toHaveCount(6);
  await page.screenshot({
    path: "test-results/hospital-network.png",
    fullPage: true,
  });
  await page.goto("/resident/report");
  await expect(
    page
      .locator(".my-reports article")
      .filter({ hasText: description })
      .getByText("completed", { exact: true }),
  ).toBeVisible();
  for (const path of [
    "response-plans",
    "vehicles",
    "hospitals",
    "dispatches",
    "communications",
  ]) {
    expect(
      (
        await request.get(`/api/${path}`, { headers: residentHeaders })
      ).status(),
    ).toBe(403);
  }
  expect(errors).toEqual([]);
});

/** Verify all workspaces, real basemap attribution and mobile layouts. */
test("desktop and mobile workspaces retain the real San Francisco map", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/coordinator/overview");
  await expect(
    page.getByRole("heading", { name: "Command Center", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".map-wrap[data-ready=true]")).toBeVisible({
    timeout: 30000,
  });
  await expect(page.locator(".maplibregl-ctrl-attrib")).toContainText(
    "OpenStreetMap",
  );
  await expect(page.getByText("All ongoing responses")).toBeVisible();
  await page.screenshot({
    path: "test-results/coordinator-overview.png",
    fullPage: true,
  });
  for (const route of [
    "incidents",
    "response-plans",
    "dispatch",
    "hospitals",
    "communications",
    "agents",
  ]) {
    await page.goto(`/coordinator/${route}`);
    await expect(page.locator(".page-heading h1")).toBeVisible();
    await expect(page.locator(".error[role=alert]")).toHaveCount(0);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of [
    "overview",
    "response-plans",
    "dispatch",
    "hospitals",
    "agents",
  ]) {
    await page.goto(`/coordinator/${route}`);
    await expect(page.locator(".page-heading h1")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await page.goto("/resident/home");
  await expect(page.locator(".bottom-nav")).toBeVisible();
  await expect(page.locator(".map-wrap[data-ready=true]")).toBeVisible({
    timeout: 30000,
  });
  await expect(page.locator(".map-caption")).toContainText("SAN FRANCISCO");
  await page.screenshot({
    path: "test-results/resident-mobile.png",
    fullPage: true,
  });
  for (const route of ["updates", "report", "help", "assistant"]) {
    await page.goto(`/resident/${route}`);
    await expect(page.locator(".page-heading h1")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  expect(errors).toEqual([]);
});
