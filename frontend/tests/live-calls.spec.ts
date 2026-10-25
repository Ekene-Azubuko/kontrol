import { expect, test } from "@playwright/test";
import type { RecordedCall } from "../lib/response-types";

/** Supply a live provider session independently of uploaded-recording fixtures. */
function liveFixture(): RecordedCall {
  return {
    id: "live-test", source: "live", has_audio: false, can_reopen: false,
    status: "live_active", received_at: "2026-10-25T12:00:00Z", sample_key: null,
    audio_content_type: "audio/wav", duration_seconds: 0, caller_latitude: null,
    caller_longitude: null, caller_accuracy_m: null, original_transcript: null,
    detected_location: null, reviewed_transcript: null, confirmed_latitude: null,
    confirmed_longitude: null, confirmed_address: null, confirmed_by: null, confirmed_at: null,
    report_id: null, incident_id: null, plan_id: null, transcription_error: null,
    attempts: 0, simulation: false, version: 1,
    live: {
      state: "active", caller: "+14155550100", called: "+14155550101",
      answered_at: "2026-10-25T12:00:00Z", ended_at: null, finalized_at: null,
      recording_state: "off", transcription_error: null, resolution_text: null,
      segments: [{ id: "segment", item_id: "item", track: "inbound", start_ms: 0,
        end_ms: 1000, text: "Market and", finalized: false }],
    },
  };
}

test("incoming calls and transcript updates arrive without refresh; start waits for finalized review", async ({ page }) => {
  const call = liveFixture();
  let visible = false;
  let starts = 0;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/events") {
      await route.fulfill({ contentType: "text/event-stream", body: 'event: refresh\ndata: {"refresh":true}\n\n' });
    } else if (path === "/api/calls/live-test/start") {
      starts += 1;
      expect(call.live?.ended_at).toBeTruthy();
      expect(call.live?.finalized_at).toBeTruthy();
      await route.fulfill({ json: { ...call, status: "confirmed", plan_id: null } });
    } else {
      await route.fulfill({ json: path === "/api/calls" ? (visible ? [call] : [])
        : path === "/api/calls/live-test" ? call : path === "/api/telephony/config" ? { enabled: false } : [] });
    }
  });
  await page.goto("/coordinator/calls");
  await expect(page.getByRole("heading", { name: "Calls", exact: true })).toBeVisible();
  visible = true;
  await expect(page.locator(".call-row")).toHaveCount(1, { timeout: 12000 });
  await page.locator(".call-row").click();
  await expect(page.getByRole("button", { name: "Start agents", exact: true })).toBeDisabled();
  await expect(page.getByLabel("Live transcript")).toContainText("Market and");
  await page.screenshot({ path: "test-results/live-call-active.png", fullPage: true });
  call.live!.segments[0].text = "Market and Eighth. One person is injured.";
  await expect(page.getByLabel("Live transcript")).toContainText("One person is injured", { timeout: 12000 });
  expect(starts).toBe(0);
  call.status = "live_finalizing";
  call.live!.ended_at = "2026-10-25T12:00:10Z";
  await expect(page.getByText("Finalizing transcript and locating the incident…")).toBeVisible({ timeout: 12000 });
  await expect(page.getByRole("button", { name: "Start agents", exact: true })).toBeDisabled();
  call.status = "awaiting_review";
  call.live!.finalized_at = "2026-10-25T12:00:11Z";
  call.live!.segments[0].finalized = true;
  call.original_transcript = "Caller: Market and Eighth. One person is injured.";
  call.detected_location = {
    status: "resolved", address: "Market and Eighth", latitude: 37.778, longitude: -122.414,
    source: "exercise_gazetteer", evidence: "Market and Eighth", reason: "Resolved exercise location",
  };
  await expect(page.getByLabel("Call type", { exact: true })).toBeVisible({ timeout: 12000 });
  await expect(page.getByRole("button", { name: "Start agents", exact: true })).toBeDisabled();
  expect(starts).toBe(0);
  await page.getByLabel("Call type", { exact: true }).selectOption("collision");
  await expect(page.getByRole("button", { name: "Start agents", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Start agents", exact: true }).click();
  await expect.poll(() => starts).toBe(1);
});
