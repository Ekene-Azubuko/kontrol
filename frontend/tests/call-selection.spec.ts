import { test, expect, type Page } from "@playwright/test";
import type { RecordedCall } from "../lib/response-types";

/** Create isolated call states without uploading recordings or running agents. */
function recording(id: string, confirmed = false): RecordedCall {
  return {
    id,
    can_reopen: false,
    status: confirmed ? "confirmed" : "awaiting_review",
    received_at: "2026-01-01T12:00:00Z",
    sample_key: null,
    audio_content_type: "audio/wav",
    duration_seconds: 20,
    caller_latitude: null,
    caller_longitude: null,
    caller_accuracy_m: null,
    original_transcript: `Fictional call ${id}.`,
    detected_location: null,
    reviewed_transcript: confirmed ? `Fictional call ${id}.` : null,
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
    version: 1,
  };
}

/** Mock every API request so switching tests cannot affect the running demo. */
async function mockCalls(page: Page, calls: RecordedCall[]) {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/audio")) {
      await route.fulfill({
        path: "../backend/app/fixtures/calls/collision.wav",
        contentType: "audio/wav",
      });
    } else if (path === "/api/calls") {
      await route.fulfill({ json: calls });
    } else if (path === "/api/events") {
      await route.fulfill({
        contentType: "text/event-stream",
        body: "data: refresh\n\n",
      });
    } else {
      const call = calls.find((item) => path === `/api/calls/${item.id}`);
      await route.fulfill({ json: call ?? [] });
    }
  });
  await page.goto("/coordinator/calls");
}

test("switching calls never retains another recording or review form", async ({
  page,
}) => {
  const calls = [
    recording("first"),
    recording("second"),
    recording("third", true),
  ];
  await mockCalls(page, calls);
  const panel = page.locator(".call-detail-body");
  for (const index of [0, 1, 0, 2, 1, 2, 0]) {
    await page.locator(".call-row").nth(index).click();
    await expect(panel.locator(".transcript:visible")).toHaveText([
      calls[index].original_transcript!,
    ]);
    await expect(panel.locator("audio")).toHaveCount(1);
    await expect(panel.locator(".call-type-form")).toHaveCount(
      index === 2 ? 0 : 1,
    );
    await expect(page.locator(".call-row")).toHaveCount(3);
  }
});

test("a corrected transcript shows once with its original collapsed", async ({
  page,
}) => {
  const call = {
    ...recording("corrected", true),
    reviewed_transcript: "Corrected fictional call.",
  };
  await mockCalls(page, [call]);
  await page.locator(".call-row").click();
  await expect(page.locator(".transcript:visible")).toHaveText([
    call.reviewed_transcript,
  ]);
  await page.getByText("Original machine transcript", { exact: true }).click();
  await expect(page.locator(".transcript:visible")).toHaveText([
    call.reviewed_transcript,
    call.original_transcript!,
  ]);
  await expect(page.locator("audio")).toHaveCount(1);
});
