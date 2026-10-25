import { test, expect, type Page } from "@playwright/test";

/** Exercise the intro without a third-party viewer or real API data. */
async function mockStartup(page: Page) {
  await page.route("**/api/**", (route) => route.fulfill({ json: [] }));
}

test("white startup screen exits and does not replay on navigation", async ({
  page,
}) => {
  const modelRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("sketchfab")) modelRequests.push(request.url());
  });
  await mockStartup(page);
  await page.goto("/coordinator/calls");
  const intro = page.getByRole("dialog", { name: "Loading Kontrol" });
  await expect(intro).toBeVisible();
  await expect(intro).toHaveCSS("background-color", "rgb(255, 255, 255)");
  await expect(intro.locator(".startup-truck-art")).toBeVisible();
  const progress = await intro.getByRole("progressbar").boundingBox();
  const wordmark = await intro
    .getByRole("heading", { name: "KONTROL" })
    .boundingBox();
  expect(wordmark!.y).toBeGreaterThan(progress!.y + progress!.height);
  await expect(intro).toHaveCount(0, { timeout: 9000 });
  expect(modelRequests).toEqual([]);
  await expect(page.locator(".startup-truck iframe")).toHaveCount(0);
  await page.getByRole("link", { name: "Command Center", exact: true }).click();
  await expect(page).toHaveURL(/\/coordinator\/overview$/);
  await expect(intro).toHaveCount(0);
});

test("mobile startup can be skipped while data is pending", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockStartup(page);
  await page.route("**/api/calls", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    await route.fulfill({ json: [] });
  });
  await page.goto("/coordinator/calls");
  await page.getByRole("button", { name: "Enter workspace" }).click();
  await expect(page.locator(".startup-screen")).toHaveCount(0);
  expect(
    await page.locator("body").evaluate((el) => el.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

test("reduced motion skips the truck animation and releases the workspace", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockStartup(page);
  await page.goto("/coordinator/calls");
  await expect(page.locator(".startup-truck iframe")).toHaveCount(0);
  await expect(page.locator(".startup-screen")).toHaveCount(0, {
    timeout: 2000,
  });
  await expect(page.locator("[inert]")).toHaveCount(0);
});

test("unresponsive data cannot trap the user in the startup screen", async ({
  page,
}) => {
  await mockStartup(page);
  await page.route("**/api/**", () => {});
  await page.goto("/coordinator/calls");
  await expect(page.locator(".startup-screen")).toHaveCount(0, {
    timeout: 9000,
  });
  await expect(page.locator("[inert]")).toHaveCount(0);
});
