import { spawn, type ChildProcess } from "node:child_process";
import http from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { API } from "./env";

// A failed API call degrades one panel, never the page. A second `next start` (same build) talks to the real API
// through a proxy that breaks two metrics: channel_days_of_stock answers with the wrong shape, dso with HTTP 500.
const PORT = 3101;
const WEB = path.join(__dirname, "..");
let proxy: http.Server;
let server: ChildProcess;

test.skip(!!process.env.SMOKE_REMOTE, "needs a local production build");

test.beforeAll(async () => {
  proxy = http.createServer(async (req, res) => {
    const chunks: Buffer[] = [];
    for await (const c of req) chunks.push(c as Buffer);
    const body = Buffer.concat(chunks).toString();
    if (req.url === "/api/metrics/query" && body.includes('"metric_name":"channel_days_of_stock"')) {
      res.writeHead(200, { "Content-Type": "application/json" }).end('{"unexpected":true}');
      return;
    }
    if (req.url === "/api/metrics/query" && body.includes('"metric_name":"dso"')) {
      res.writeHead(500, { "Content-Type": "application/json" }).end('{"detail":"injected failure"}');
      return;
    }
    const headers = Object.fromEntries(Object.entries(req.headers).filter(([k]) => !["host", "content-length", "connection"].includes(k))) as Record<string, string>;
    const upstream = await fetch(API + req.url, { method: req.method, headers, body: req.method === "GET" ? undefined : body });
    res.writeHead(upstream.status, { "Content-Type": upstream.headers.get("content-type") ?? "application/json" }).end(Buffer.from(await upstream.arrayBuffer()));
  });
  await new Promise<void>((resolve) => proxy.listen(0, "127.0.0.1", resolve));
  const proxyUrl = `http://127.0.0.1:${(proxy.address() as AddressInfo).port}`;

  server = spawn(process.execPath, [require.resolve("next/dist/bin/next"), "start", "-p", String(PORT)], {
    cwd: WEB,
    env: { ...process.env, CHANNELPULSE_API_URL: proxyUrl },
    stdio: "ignore",
  });
  await expect.poll(async () => (await fetch(`http://127.0.0.1:${PORT}/ask`).catch(() => null))?.status ?? 0, { timeout: 30_000 }).toBe(200);
});

test.afterAll(async () => {
  server?.kill();
  await new Promise((resolve) => proxy?.close(resolve));
});

test("broken metrics degrade their own panels only", async ({ page }) => {
  const uncaught: string[] = [];
  page.on("pageerror", (e) => uncaught.push(e.message));
  await page.goto(`http://127.0.0.1:${PORT}/`);
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
