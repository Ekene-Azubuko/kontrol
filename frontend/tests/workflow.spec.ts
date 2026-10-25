import { test, expect } from "@playwright/test";
import type {
  RecordedCall,
  ResponsePlan,
  Hospital,
  Dispatch,
} from "../lib/response-types";
const headers = { Authorization: "Bearer demo-coordinator" };

/** Correct a failed location, preserve the call type, and replay the reveal even for unchanged coordinates. */
test("edit address and find location again", async ({ page, request }) => {
  test.setTimeout(90000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/coordinator/calls");
  const created = page.waitForResponse((response) =>
    response.url().endsWith("/api/calls/sample/collision"),
  );
  await page
    .getByRole("button", {
      name: "Load sample call: Multi-vehicle collision",
      exact: true,
    })
    .click();
  const call: RecordedCall = await (await created).json();
  const map = page.locator(".call-location-map");
  await expect(map).toHaveAttribute("data-location-phase", "pinned", {
    timeout: 30000,
  });
  const original: RecordedCall = await (
    await request.get(`/api/calls/${call.id}`, { headers })
  ).json();
  await page
    .getByRole("combobox", { name: "Call type", exact: true })
    .selectOption("collision");
  const start = page.getByRole("button", { name: "Start agents", exact: true });
  await page.getByRole("button", { name: "Edit address", exact: true }).click();
  const address = page.getByRole("textbox", {
    name: "Incident address or intersection",
  });
  await address.fill("Unknown location");
  await expect(start).toBeDisabled();
  await page
    .getByRole("button", { name: "Find location again", exact: true })
    .click();
  await expect(page.locator(".call-location-unavailable")).toContainText(
    "Location unavailable",
  );
  await expect(map).toHaveCount(0);
  await expect(start).toBeDisabled();
  await address.fill("Mission exercise block");
  await page.screenshot({
    path: "test-results/edit-address.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Find location again", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Mission exercise block", exact: true }),
  ).toBeVisible();
  await expect(map).toHaveAttribute("data-location-phase", "flying", {
    timeout: 20000,
  });
  await expect(map).toHaveAttribute("data-location-phase", "pinned");
  await expect(start).toBeEnabled();
  await expect(
    page.getByRole("combobox", { name: "Call type", exact: true }),
  ).toHaveValue("collision");
  const oldMap = await map.elementHandle();
  await page
    .getByRole("button", { name: "Find location again", exact: true })
    .click();
  await expect(map).toHaveAttribute("data-location-phase", "flying", {
    timeout: 20000,
  });
  expect(await oldMap!.evaluate((element) => element.isConnected)).toBe(false);
  await expect(map).toHaveAttribute("data-location-phase", "pinned");
  const edited: RecordedCall = await (
    await request.get(`/api/calls/${call.id}`, { headers })
  ).json();
  expect(edited.original_transcript).toBe(original.original_transcript);
  expect(edited.attempts).toBe(original.attempts);
  expect(edited.detected_location?.input_source).toBe("dispatcher_address");
  expect(edited.detected_location?.input_address).toBe(
    "Mission exercise block",
  );
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page
    .getByRole("button", { name: "Find location again", exact: true })
    .click();
  await expect(map).toHaveAttribute("data-location-phase", "pinned", {
    timeout: 20000,
  });
  await expect(page.locator(".incident-drop-pin")).toHaveCSS(
    "animation-name",
    "none",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Edit address", exact: true }).click();
  await expect(address).toHaveValue("Mission exercise block");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/edit-address-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(start).toBeEnabled();
  expect(errors).toEqual([]);
});

/** Exercise real proxy uploads, transcript review, durable agents and stationary approved markers. */
test("sample call → animated location → call type → agents → static approved markers", async ({
  page,
  request,
}) => {
  test.setTimeout(180000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  expect(
    (
      await request.post("/api/response-demo", {
        headers,
        data: { action: "reset" },
      })
    ).ok(),
  ).toBeTruthy();
  await page.goto("/coordinator/calls");
  await expect(page.locator("footer")).toContainText(
    "SIMULATION (NOT FOR EMERGENCY USE)",
  );
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/calls/sample/collision") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", {
      name: "Load sample call: Multi-vehicle collision",
      exact: true,
    })
    .click();
  const call: RecordedCall = await (await created).json();
  await expect(
    page.getByRole("heading", {
      name: "Market & 8th exercise area",
      exact: true,
    }),
  ).toBeVisible({ timeout: 30000 });
  await expect(page.locator("audio")).toHaveAttribute("src", /^blob:/);
  await expect
    .poll(
      () =>
        page
          .locator("audio")
          .evaluate((element) => (element as HTMLAudioElement).readyState),
      { timeout: 15000 },
    )
    .toBeGreaterThan(0);
  await expect(page.locator("textarea")).toHaveCount(0);
  await expect(
    page.locator('input[type="number"], input[type="checkbox"]'),
  ).toHaveCount(0);
  await expect(page.locator(".call-location-map")).toHaveAttribute(
    "data-location-phase",
    "pinned",
    { timeout: 30000 },
  );
  await expect(page.locator(".incident-drop-anchor")).toBeVisible();
  await page.screenshot({
    path: "test-results/automatic-location.png",
    fullPage: true,
  });
  await page
    .getByRole("combobox", { name: "Call type", exact: true })
    .selectOption("collision");
  const confirmed = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/calls/${call.id}/start`) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Start agents", exact: true }).click();
  const startResponse = await confirmed;
  expect(Object.keys(startResponse.request().postDataJSON()).sort()).toEqual([
    "category",
    "version",
  ]);
  const review: RecordedCall = await startResponse.json();
  expect(review.original_transcript).toEqual(review.reviewed_transcript);
  expect(review.confirmed_latitude).toBe(37.777);
  let plan: ResponsePlan;
  await expect
    .poll(
      async () => {
        plan = await (
          await request.get(`/api/response-plans/${review.plan_id}`, {
            headers,
          })
        ).json();
        return plan.status;
      },
      { timeout: 45000 },
    )
    .toBe("needs_information");
  expect(plan!.runs.map((run) => run.stage).sort()).toEqual([
    "dispatch",
    "hospital",
    "intake",
    "planning",
  ]);
  expect(plan!.requirements.estimated_patients).toBe(2);
  expect(plan!.constraints.join(" ")).toContain("unconfirmed");
  expect((await request.get("/api/dispatches", { headers })).ok()).toBeTruthy();
  const baseline: Hospital[] = await (
    await request.get("/api/hospitals", { headers })
  ).json();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "Proposed assignments", exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await expect(
    dialog
      .locator("summary")
      .filter({ hasText: /^Call transcript provenance$/ }),
  ).toBeVisible();
  await dialog
    .locator("textarea")
    .fill(
      "Reviewed fictional transcript, location, and provisional destination.",
    );
  await dialog
    .getByRole("button", { name: "Approve plan", exact: true })
    .click();
  await expect.poll(async () => (
    await (await request.get(`/api/response-plans/${review.plan_id}`, { headers })).json()
  ).status).toBe("approved");
  await dialog.getByRole("button", { name: "Close details" }).click();
  await page.goto("/coordinator/overview");
  await expect(page.locator(".map-wrap[data-ready=true]")).toBeVisible();
  const markers = page.locator(".map-marker.vehicle");
  await expect(markers).toHaveCount(plan!.assignments.length);
  const positions = await markers.evaluateAll((elements) => elements.map((element) => (element as HTMLElement).style.transform));
  // Observe beyond the retired timer's first travel step, including ordinary SSE refreshes.
  await page.waitForTimeout(14000);
  await expect(markers).toHaveCount(plan!.assignments.length);
  expect(await markers.evaluateAll((elements) => elements.map((element) => (element as HTMLElement).style.transform))).toEqual(positions);
  const persisted: ResponsePlan = await (await request.get(`/api/response-plans/${review.plan_id}`, { headers })).json();
  expect(persisted.status).toBe("approved");
  const dispatches: Dispatch[] = await (await request.get("/api/dispatches", { headers })).json();
  expect(dispatches.filter((dispatch) => dispatch.plan_id === persisted.id).every(
    (dispatch) => dispatch.status === "assigned" && dispatch.progress === 0 && !dispatch.released_at,
  )).toBeTruthy();
  const final: Hospital[] = await (await request.get("/api/hospitals", { headers })).json();
  expect(final.reduce((sum, hospital) => sum + (hospital.occupied_beds || 0), 0)).toBe(
    baseline.reduce((sum, hospital) => sum + (hospital.occupied_beds || 0), 0),
  );
  expect((await request.get("/api/communications", { headers })).status()).toBe(404);
  await page.screenshot({ path: "test-results/call-plan-static-markers.png", fullPage: true });
  expect(errors).toEqual([]);
});

/** The browser must send genuine multipart bytes and surface mock failures and retries. */
test("fictional upload without automatic location fails clearly in mock mode and can retry", async ({
  page,
}) => {
  await page.goto("/coordinator/calls");
  const wav = Buffer.alloc(44 + 32000);
  wav.write("RIFF", 0);
  wav.writeUInt32LE(wav.length - 8, 4);
  wav.write("WAVEfmt ", 8);
  wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20);
  wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(16000, 24);
  wav.writeUInt32LE(32000, 28);
  wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34);
  wav.write("data", 36);
  wav.writeUInt32LE(32000, 40);
  const uploaded = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/calls") &&
      response.request().method() === "POST",
  );
  await page.locator('input[type="file"]').setInputFiles({
    name: "fictional.wav",
    mimeType: "audio/wav",
    buffer: wav,
  });
  expect((await uploaded).status()).toBe(201);
  await expect(page.locator(".error[role=alert]")).toContainText(
    "Transcription supports bundled samples only",
    { timeout: 30000 },
  );
  const retried = page.waitForResponse((response) =>
    response.url().endsWith("/retry-transcription"),
  );
  await page.getByRole("button", { name: "Retry transcription" }).click();
  expect((await retried).status()).toBe(200);
  await expect(page.locator(".error[role=alert]")).toContainText(
    "Transcription supports bundled samples only",
    { timeout: 30000 },
  );
});

/** Retired portals stay inaccessible and dispatcher pages remain usable on small screens. */
test("dispatcher navigation and retired resident routes", async ({ page }) => {
  for (const route of ["home", "updates", "report", "help", "assistant"]) {
    expect((await page.goto(`/resident/${route}`))!.status()).toBe(404);
  }
  for (const route of ["resources", "hospitals", "communications"]) {
    expect((await page.goto(`/coordinator/${route}`))!.status()).toBe(404);
  }
  await page.goto("/");
  await expect(page).toHaveURL(/\/coordinator\/overview$/);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of [
    "calls",
    "overview",
    "incidents",
    "response-plans",
    "dispatch",
    "agents",
  ]) {
    await page.goto(`/coordinator/${route}`);
    await expect(page.locator(".page-heading h1")).toBeVisible();
    await expect(page.locator("footer")).toContainText(
      "SIMULATION (NOT FOR EMERGENCY USE)",
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await page.screenshot({
    path: "test-results/dispatcher-mobile.png",
    fullPage: true,
  });
});

/** Motion-sensitive users get the same inferred pin without a camera flight or CSS bounce. */
test("automatic location respects reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/coordinator/calls");
  await page
    .getByRole("button", {
      name: "Load sample call: Reported cardiac arrest",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("heading", { name: "Mission exercise block", exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".call-location-map")).toHaveAttribute(
    "data-location-phase",
    "pinned",
    { timeout: 30000 },
  );
  await expect(page.locator(".incident-drop-pin")).toHaveCSS(
    "animation-name",
    "none",
  );
  await expect(
    page.getByRole("button", { name: "Start agents", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("combobox", { name: "Call type", exact: true })
    .selectOption("medical");
  await expect(
    page.getByRole("button", { name: "Start agents", exact: true }),
  ).toBeEnabled();
});
