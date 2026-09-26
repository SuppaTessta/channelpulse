import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { API } from "./env";

// Every page, in the public claim and one region: no uncaught exception, no console error, and no panel left
// loading or in an error state (anything carrying data-panel-error: ErrorState, a failed chart, the page boundary).

const REGIONS = [
  { name: "All regions", query: "" },
  { name: "Assam", query: "?region=assam" },
];
const PAGES = ["/", "/distributors", "/quality", "/ask"];

// Both crashes seen before Phase 2 were stale processes (decisions D28). Name them outright instead of letting the
// page tests fail on their symptoms.
test("the dashboard server is running the build on disk", async ({ request }) => {
  const idFile = path.join(__dirname, "..", ".next", "BUILD_ID");
  test.skip(!existsSync(idFile) || !!process.env.SMOKE_REMOTE, "no local production build to compare against");
  const html = await (await request.get("/ask")).text();
  const onDisk = readFileSync(idFile, "utf8").trim();
  expect(html.includes(onDisk), `the server is older than .next (build ${onDisk}): restart it (make web-start)`).toBe(true);
});

test("the API is running current code", async ({ request }) => {
  const res = await request.get(`${API}/api/meta`);
  expect(res.status(), `${API}/api/meta must exist; a 404 means an API process older than the code: restart it`).toBe(200);
  expect(Object.keys(await res.json()).sort()).toEqual(["as_of", "data_start", "provisional_days", "regions"]);
});

function watchErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`uncaught: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console.error: ${m.text()}`);
  });
  return errors;
}

async function settle(page: Page) {
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  // Plot draws after the chart library loads: an empty plot host is a chart that never drew.
  await expect(page.locator(".cp-plot:empty")).toHaveCount(0);
}

async function expectHealthy(page: Page, errors: string[]) {
  await settle(page);
  await expect(page.getByText("Application error")).toHaveCount(0);
  const panelErrors = await page.locator("[data-panel-error]").allInnerTexts();
  expect(panelErrors, "panels in an error state").toEqual([]);
  expect(errors, "console errors and uncaught exceptions").toEqual([]);
}

for (const region of REGIONS) {
  for (const path of PAGES) {
    test(`${path} in ${region.name}`, async ({ page }) => {
      const errors = watchErrors(page);
      await page.goto(path + region.query);
      await expectHealthy(page, errors);
    });
  }

  test(`/distributors/[id] in ${region.name}`, async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto("/distributors" + region.query);
    await settle(page);
    const href = await page.locator('a[href^="/distributors/"]').first().getAttribute("href");
    expect(href, "the distributor list links to a distributor").toBeTruthy();
    await page.goto(href!);
    await expectHealthy(page, errors);
  });
}

// Without a live analyst the Ask page explains itself (replay, or an honest empty state), never an error.
test("/ask without a live analyst shows replay mode or says why not", async ({ page, request }) => {
  const status = await (await request.get(`${API}/api/ask/status`)).json();
  test.skip(status.mode === "live", "this API answers live");
  const errors = watchErrors(page);
  await page.goto("/ask");
  await expectHealthy(page, errors);
  await expect(page.getByRole("heading", { name: /Replay mode|live analyst/ })).toBeVisible();
});

