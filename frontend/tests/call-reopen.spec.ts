import { test, expect } from "@playwright/test";
import type { RecordedCall, ResponsePlan } from "../lib/response-types";

const headers = { Authorization: "Bearer demo-coordinator" };

/** Return from plan review to the same recording, then run a new category through all four agents. */
test("back to call type preserves recording and starts a fresh workflow", async ({ page, request }) => {
  test.setTimeout(120000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/coordinator/calls");
  const created = page.waitForResponse((r) => r.url().endsWith("/api/calls/sample/collision"));
  await page.getByRole("button", { name: "Load sample call: Multi-vehicle collision", exact: true }).click();
  const original: RecordedCall = await (await created).json();
  const type = page.getByRole("combobox", { name: "Call type", exact: true });
  await type.selectOption("collision");
  const started = page.waitForResponse((r) => r.url().endsWith(`/api/calls/${original.id}/start`));
  await page.getByRole("button", { name: "Start agents", exact: true }).click();
  const first: RecordedCall = await (await started).json();
  const originalAudio = await (await request.get(`/api/calls/${original.id}/audio`, { headers })).body();
  await expect.poll(async () => (await (await request.get(`/api/response-plans/${first.plan_id}`, { headers })).json()).status,
    { timeout: 45000 }).toBe("awaiting_approval");
  const oldPlan: ResponsePlan = await (await request.get(`/api/response-plans/${first.plan_id}`, { headers })).json();

  // Exercise navigation from the separate plan page, not just closing the call's drawer.
  await page.goto("/coordinator/response-plans");
  await page.locator(".plan-card").filter({ hasText: first.plan_id!.slice(0, 6).toUpperCase() }).click();
  const dialog = page.getByRole("dialog");
  const returned = page.waitForResponse((r) => r.url().endsWith(`/api/calls/${original.id}/reopen`));
  await dialog.getByRole("button", { name: "Back to call type", exact: true }).click();
  const reopened: RecordedCall = await (await returned).json();
  await expect(page).toHaveURL(new RegExp(`/coordinator/calls\\?call=${original.id}$`));
  await expect(type).toBeVisible();
  await expect(type).toHaveValue("");
  await expect(page.getByRole("button", { name: "Start agents", exact: true })).toBeDisabled();
  await expect(page.locator("audio")).toHaveAttribute("src", /^blob:/);
  expect(reopened.original_transcript).toBe(first.original_transcript);
  expect(reopened.detected_location).toEqual(first.detected_location);
  expect(reopened.attempts).toBe(first.attempts);
  expect(await (await request.get(`/api/calls/${original.id}/audio`, { headers })).body()).toEqual(originalAudio);
  expect((await (await request.get(`/api/response-plans/${first.plan_id}`, { headers })).json()).status).toBe("cancelled");
  expect(reopened.plan_id).toBeNull();

  await page.setViewportSize({ width: 390, height: 844 });
  await type.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/back-to-call-type-mobile.png" });
  await type.selectOption("medical");
  const restarted = page.waitForResponse((r) => r.url().endsWith(`/api/calls/${original.id}/start`));
  await page.getByRole("button", { name: "Start agents", exact: true }).click();
  const fresh: RecordedCall = await (await restarted).json();
  expect(fresh.id).toBe(first.id);
  expect(fresh.plan_id).not.toBe(first.plan_id);
  await expect.poll(async () => (await (await request.get(`/api/response-plans/${fresh.plan_id}`, { headers })).json()).status,
    { timeout: 45000 }).toBe("awaiting_approval");
  const freshPlan: ResponsePlan = await (await request.get(`/api/response-plans/${fresh.plan_id}`, { headers })).json();
  expect(freshPlan.runs).toHaveLength(4);
  expect(freshPlan.runs.every((r) => oldPlan.runs.every((old) => old.id !== r.id))).toBe(true);
  const intake = freshPlan.runs.find((r) => r.stage === "intake")!;
  expect((intake.input.agent_input as { category: string }).category).toBe("medical");

  // The call view also exposes the same return action after closing the plan drawer.
  await dialog.getByRole("button", { name: "Close details", exact: true }).click();
  await page.getByRole("button", { name: "Back to call type", exact: true }).click();
  await expect(type).toBeVisible();
  await expect(type).toHaveValue("");
  expect(errors).toEqual([]);
});
