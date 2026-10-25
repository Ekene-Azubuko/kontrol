import { test, expect, type Page } from "@playwright/test";
import type { RecordedCall } from "../lib/response-types";

const recording: RecordedCall = {
  id: "7de131b0-535e-42da-a54c-dd4972ff6e80",
  can_reopen: false,
  status: "failed",
  received_at: "2026-01-01T12:00:00Z",
  sample_key: null,
  audio_content_type: "audio/wav",
  duration_seconds: 20,
  caller_latitude: null,
  caller_longitude: null,
  caller_accuracy_m: null,
  original_transcript: null,
  detected_location: null,
  reviewed_transcript: null,
  confirmed_latitude: null,
  confirmed_longitude: null,
  confirmed_address: null,
  confirmed_by: null,
  confirmed_at: null,
  report_id: null,
  incident_id: null,
  plan_id: null,
  transcription_error: null,
  attempts: 1,
  simulation: true,
  version: 3,
};

/** Keep UI deletion tests isolated from real recordings and all provider work. */
async function mockRecordings(page: Page, conflict = false) {
  const state = {
    deletes: 0,
    recordings: [recording, { ...recording, id: "other-recording" }],
  };
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "DELETE") {
      expect(path).toBe(`/api/calls/${recording.id}`);
      expect(route.request().postDataJSON()).toEqual({
        version: recording.version,
      });
      state.deletes += 1;
      if (conflict) {
        await route.fulfill({
          status: 409,
          json: {
            detail: "Recording changed. Refresh and confirm deletion again.",
          },
        });
      } else {
        state.recordings = state.recordings.filter(
          (item) => item.id !== recording.id,
        );
        await route.fulfill({
          json: { id: recording.id, deleted: true, cleanup_pending: false },
        });
      }
    } else if (path.endsWith("/audio")) {
      await route.fulfill({
        path: "../backend/app/fixtures/calls/collision.wav",
        contentType: "audio/wav",
      });
    } else if (path === "/api/calls") {
      await route.fulfill({ json: state.recordings });
    } else if (path === `/api/calls/${recording.id}`) {
      await route.fulfill({ json: recording });
    } else if (path === "/api/events") {
      await route.fulfill({
        contentType: "text/event-stream",
        body: "data: refresh\n\n",
      });
    } else {
      await route.fulfill({ json: [] });
    }
  });
  await page.goto(`/coordinator/calls?call=${recording.id}`);
  await expect(page.locator("audio")).toBeVisible();
  return state;
}

test("recording deletion is confirmed and clears its deep link and selection", async ({
  page,
}) => {
  const state = await mockRecordings(page);
  await page
    .getByRole("button", { name: "Delete recording", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Delete recording?",
    exact: true,
  });
  await expect(dialog).toContainText("Ongoing responses are not cancelled");
  await expect(
    dialog.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeFocused();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(state.deletes).toBe(0);
  await expect(page.locator(".call-row")).toHaveCount(2);
  await page
    .getByRole("button", { name: "Delete recording", exact: true })
    .click();
  await dialog
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".call-row")).toHaveCount(1);
  await expect(page.locator("audio")).toHaveCount(0);
  await expect(page).toHaveURL(/\/coordinator\/calls$/);
  expect(state.deletes).toBe(1);
  await page.reload();
  await expect(page.locator(".call-row")).toHaveCount(1);
  await expect(page.locator(".call-detail-body")).toContainText(
    "Select a call",
  );
});

test("stale deletion keeps the recording and shows a useful error on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = await mockRecordings(page, true);
  await page
    .getByRole("button", { name: "Delete recording", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Delete recording?",
    exact: true,
  });
  await dialog
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("Recording changed");
  expect(state.deletes).toBe(1);
  await expect(page.locator(".call-row")).toHaveCount(2);
  expect(
    await dialog.evaluate(
      (element) => element.scrollWidth > element.clientWidth,
    ),
  ).toBe(false);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.locator("audio")).toBeVisible();
});
