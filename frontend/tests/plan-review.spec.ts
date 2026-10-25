import { test, expect } from "@playwright/test";
import { reviewFixture } from "./plan-review-fixture";

/** Compare real rendered map/list interactions while keeping verbose synthetic records outside the running database. */
test("compact review preserves full notes and compares nearest versus recommended hospitals", async ({
  page,
}) => {
  test.setTimeout(90000);
  const plan = reviewFixture();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/response-plans", (route) =>
    route.fulfill({ json: [plan] }),
  );
  await page.route(`**/api/response-plans/${plan.id}`, (route) =>
    route.fulfill({ json: plan }),
  );
  await page.goto("/coordinator/response-plans");
  await page
    .getByRole("button")
    .filter({ has: page.getByRole("heading", { name: plan.incident.title }) })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "Quick review checks" }),
  ).toBeVisible();
  await expect(dialog.locator(".review-check-grid > div")).toHaveCount(4);
  await expect(
    dialog.getByText("No accessible rescue unit was supplied.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    dialog.getByText(plan.constraints[0], { exact: true }),
  ).not.toBeVisible();
  await expect(dialog.locator(".plan-summary")).not.toContainText(
    "Full agent plan narrative",
  );
  const notes = dialog.locator(".review-full-notes");
  await notes.locator("summary").click();
  await expect(notes.locator("li")).toHaveCount(23);
  await expect(
    notes.getByText(plan.constraints[22], { exact: true }),
  ).toBeVisible();
  await notes.locator("summary").click();
  const rows = dialog.locator(".hospital-comparison-list > li");
  await expect(rows.first()).toContainText("SIM · Near Hospital");
  await expect(rows.last()).toContainText("Agent choice #1");
  await expect(rows.first()).toContainText("Beds unknown");
  await expect(rows.first()).toContainText("Travel time unknown");
  await expect(
    dialog.getByText(plan.runs[0].output!.reasoning!, { exact: true }),
  ).not.toBeVisible();
  await dialog
    .getByRole("combobox", { name: "Sort hospitals" })
    .selectOption("farthest");
  await expect(rows.first()).toContainText("SIM · Far Hospital");
  await expect(rows.first()).toHaveAttribute("data-distance-rank", "3");
  await dialog
    .getByRole("combobox", { name: "Sort hospitals" })
    .selectOption("recommended");
  await expect(rows.first()).toContainText("SIM · Far Hospital");
  await dialog
    .getByRole("combobox", { name: "Sort hospitals" })
    .selectOption("nearest");
  await dialog
    .getByRole("button", {
      name: "Highlight SIM · Near Hospital on map",
      exact: true,
    })
    .click();
  const nearPin = dialog.getByRole("button", {
    name: /^1\. SIM · Near Hospital/,
  });
  await expect(nearPin).toHaveText("1");
  await expect(nearPin).toHaveAttribute("aria-pressed", "true");
  await expect(dialog.locator(".plan-hospitals .map-wrap")).toHaveAttribute(
    "data-ready",
    "true",
    { timeout: 30000 },
  );
  const farPin = dialog.getByRole("button", {
    name: /^3\. SIM · Far Hospital/,
  });
  await dialog.locator(".plan-hospitals .map-wrap").scrollIntoViewIfNeeded();
  await farPin.click();
  await expect(rows.last()).toHaveClass("selected");
  await expect(dialog.locator(".map-caption")).toContainText(
    "HOSPITAL OPTIONS",
  );
  const fullReasoning = dialog
    .locator("summary")
    .filter({ hasText: /^Full hospital reasoning$/ });
  await fullReasoning.click();
  await expect(
    dialog.getByText(plan.runs[0].output!.reasoning!, { exact: true }),
  ).toBeVisible();
  await fullReasoning.click();
  await dialog
    .getByRole("heading", { name: "Hospital options" })
    .scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/hospital-distance-review.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    dialog.getByRole("combobox", { name: "Sort hospitals" }),
  ).toBeVisible();
  expect(
    await dialog.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/hospital-distance-review-mobile.png",
  });
  expect(errors).toEqual([]);
});
