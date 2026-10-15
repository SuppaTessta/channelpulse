import { spawn, type ChildProcess } from "node:child_process";
import http from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { API } from "./env";

// Fault injection. Each block starts a second `next start` (same build) that talks to the real API through a proxy
// that misbehaves on purpose. The blocks share this file so they run one after the other, in one worker: two extra
// dashboards loading full pages at once would slow the local API into timeouts of its own.
const WEB = path.join(__dirname, "..");

test.skip(!!process.env.SMOKE_REMOTE, "needs a local production build");

type Fault = (req: http.IncomingMessage, body: string, res: http.ServerResponse) => boolean;

/** A proxy to the real API that lets `fault` answer instead, and a dashboard on `port` pointed at it. */
function harness(port: number, fault: Fault, env: Record<string, string> = {}) {
  let proxy: http.Server;
  let server: ChildProcess;
  test.beforeAll(async () => {
    proxy = http.createServer(async (req, res) => {
      const chunks: Buffer[] = [];
      for await (const c of req) chunks.push(c as Buffer);
      const body = Buffer.concat(chunks).toString();
      if (fault(req, body, res)) return;
      const headers = Object.fromEntries(Object.entries(req.headers).filter(([k]) => !["host", "content-length", "connection"].includes(k))) as Record<string, string>;
      const upstream = await fetch(API + req.url, { method: req.method, headers, body: req.method === "GET" ? undefined : body });
      res.writeHead(upstream.status, { "Content-Type": upstream.headers.get("content-type") ?? "application/json" }).end(Buffer.from(await upstream.arrayBuffer()));
    });
    await new Promise<void>((resolve) => proxy.listen(0, "127.0.0.1", resolve));
    const proxyUrl = `http://127.0.0.1:${(proxy.address() as AddressInfo).port}`;
    server = spawn(process.execPath, [require.resolve("next/dist/bin/next"), "start", "-p", String(port)], {
      cwd: WEB,
      env: { ...process.env, CHANNELPULSE_API_URL: proxyUrl, ...env },
      stdio: "ignore",
    });
    await expect.poll(async () => (await fetch(`http://127.0.0.1:${port}/ask`).catch(() => null))?.status ?? 0, { timeout: 30_000 }).toBe(200);
  });
  test.afterAll(async () => {
    server?.kill();
    await new Promise((resolve) => proxy?.close(resolve));
  });
}

test.describe("a failed API call degrades one panel, never the page", () => {
  // channel_days_of_stock answers with the wrong shape, dso with HTTP 500.
  harness(3101, (req, body, res) => {
    if (req.url === "/api/metrics/query" && body.includes('"metric_name":"channel_days_of_stock"')) {
      res.writeHead(200, { "Content-Type": "application/json" }).end('{"unexpected":true}');
      return true;
    }
    if (req.url === "/api/metrics/query" && body.includes('"metric_name":"dso"')) {
      res.writeHead(500, { "Content-Type": "application/json" }).end('{"detail":"injected failure"}');
      return true;
    }
    return false;
  });

  test("broken metrics degrade their own panels only", async ({ page }) => {
    const uncaught: string[] = [];
    page.on("pageerror", (e) => uncaught.push(e.message));
    await page.goto("http://127.0.0.1:3101/");
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);

    const panel = (id: string) => page.locator(`section[aria-labelledby="${id}"]`);
    await expect(panel("stock").locator("[data-panel-error]")).toContainText("can't read");
    await expect(panel("dso").locator("[data-panel-error]")).toContainText("Retry");
    // The neighbours still draw.
    await expect(panel("sales").locator("[data-panel-error]")).toHaveCount(0);
    await expect(panel("sales").locator(".cp-plot svg")).toHaveCount(1);
    await expect(page.getByRole("heading", { name: "Stock-out and overstock by region" })).toBeVisible();
    expect(uncaught).toEqual([]);
    await page.screenshot({ path: test.info().outputPath("degraded.png"), fullPage: true });
  });
});

test.describe("a sleeping free-tier API shows a waking-up state (D49)", () => {
  // While it wakes, the host answers with an HTML 503 instead of the API's JSON.
  let asleep = true;
  harness(3102, (_req, _body, res) => {
    if (!asleep) return false;
    res.writeHead(503, { "Content-Type": "text/html" }).end("<html><body>Service waking up</body></html>");
    return true;
  }, { CHANNELPULSE_API_COLD_STARTS: "1" });

  test("the page says the API is waking up, then fills in on its own", async ({ page }) => {
    test.setTimeout(120_000);
    const uncaught: string[] = [];
    page.on("pageerror", (e) => uncaught.push(e.message));
    await page.goto("http://127.0.0.1:3102/");
    // The page's first call (the data window) already meets the sleeping host, so the whole page says so, calmly.
    await expect(page.locator("[data-panel-error]").first()).toContainText("The API is waking up");
    await expect(page.getByText("The API didn't answer in time")).toHaveCount(0);
    await page.screenshot({ path: test.info().outputPath("waking.png"), fullPage: true });

    asleep = false; // the API is up: no click, the page retries by itself
    const sales = page.locator('section[aria-labelledby="sales"]');
    await expect(sales.locator(".cp-plot svg")).toHaveCount(1, { timeout: 90_000 });
    await expect(sales.locator("[data-panel-error]")).toHaveCount(0);
    expect(uncaught).toEqual([]);
  });
});

// Next 15.5 sometimes never applies a streamed client navigation: on a cold cache about half of region switches
// stayed dimmed on the old page for good (decisions D53). Stalling the navigation's RSC fetch reproduces that state.
test("a filter change that never applies falls back to loading the page in full", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
  await page.route(/[?&]_rsc=/, async (route) => {
    if (!route.request().url().includes("region=")) await route.continue(); // a region navigation's fetch never answers
  });
  await page.getByRole("combobox", { name: "Viewing as" }).click();
  await page.getByRole("option", { name: "Assam" }).click();
  await expect(page).toHaveURL(/region=assam/, { timeout: 30_000 });
  await expect(page.getByRole("combobox", { name: "Viewing as" })).toHaveText("Assam");
});

// Links stall the same way (D53): about one in four cold distributor pages never opened from the list.
test("a link that never applies falls back to loading the page in full", async ({ page }) => {
  await page.goto("/distributors?q=D0001");
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
  await page.route(/[?&]_rsc=/, async (route) => {
    if (!route.request().url().includes("/distributors/D0001")) await route.continue(); // the link's fetch never answers
  });
  await page.getByRole("link", { name: "Tarun Sharma Trading Co." }).click();
  await expect(page).toHaveURL(/\/distributors\/D0001/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Tarun Sharma Trading Co.");
});

// The watchdog stands down once the URL has moved by any route (final review #1): it used to fire 12 s later even
// after the user had arrived and gone back, yanking them forward with a full reload.
test.describe("the navigation watchdog never fires after the URL has moved", () => {
  test.setTimeout(90_000);
  test("closing a trace drawer stays closed", async ({ page }) => {
    await page.goto("/traces");
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
    await page.locator("table tbody tr a").first().click();
    await expect(page).toHaveURL(/trace=/);
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page).not.toHaveURL(/trace=/);
    await page.waitForTimeout(13_000);
    await expect(page).not.toHaveURL(/trace=/);
  });
  test("going back from a distributor stays on the list", async ({ page }) => {
    await page.goto("/distributors");
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
    await page.locator("table tbody tr a").first().click();
    await expect(page).toHaveURL(/\/distributors\/D\d+/);
    await page.goBack();
    await expect(page).toHaveURL(/\/distributors$/);
    await page.waitForTimeout(13_000);
    await expect(page).toHaveURL(/\/distributors$/);
  });
});
