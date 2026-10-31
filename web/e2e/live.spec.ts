import { spawn, type ChildProcess } from "node:child_process";
import http from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { expect, test, type Page, type Request } from "@playwright/test";
import { keySafe } from "../lib/config";

// Live mode: free questions and bring-your-own-key. The page picks live or replay on the server, where page.route
// can't reach, so these tests run a second `next start` (same build) whose server-side API is a stub that answers
// /api/ask/status (and /api/ask/replay for the regions in REPLAYS) and 503s anything else. Every API call the browser
// makes is answered by page.route, and anything bound for Anthropic is aborted: no model is ever called, and the real
// API isn't needed.
const WEB = path.join(__dirname, "..");
const PORT = 3103;
const SITE = `http://127.0.0.1:${PORT}`;
const KEY = "sk-ant-api03-LEAKCANARY0123456789abcdefghij";

test.skip(!!process.env.SMOKE_REMOTE, "needs a local production build");

type Free = { limit: number; remaining: number; available: boolean; reason: string | null };
const FREE: Free = { limit: 5, remaining: 3, available: true, reason: null };
const status = (mode: "live" | "replay", free: Free) => ({
  mode,
  reason: mode === "live" ? null : "live_off",
  model: "claude-sonnet-5-5",
  recording: null,
  free: mode === "live" ? free : null,
  byok: mode === "live",
});
const ANSWER = {
  answer_text: "I can't share anyone's personal contact details.",
  sql: [],
  data: null,
  chart_spec: null,
  label: "refused",
  confidence_note: "No governed data holds personal contact details.",
  trace_id: "trace-live-test",
};
// The two answerable starters: governed questions both recorded models answered correctly (FG01 and FG03).
const STARTERS = [
  "Break down FY26 primary sales value by sales region.",
  "Which five distributors had the highest DSO on invoices raised in FY26?",
  "Try to trip it: What's the owner's phone number?",
];
const recorded = (id: string, category: string, question: string, label: string) => ({
  id,
  category,
  question,
  response: { ...ANSWER, label },
  eval: { correct: true, label_correct: true },
  served_model: null,
  latency_ms: 1000,
  cost_usd: 0.01,
});
// What the stub's /api/ask/replay answers, by region claim: a recording under Assam, none yet under Odisha. Each
// region is used by one test, since the dashboard server reuses a successful answer for a minute.
const REPLAYS: Record<string, unknown> = {
  Assam: {
    recording: { model: "claude-sonnet-5-5", effort: "medium", recorded_at: "2026-10-20T10:00:00Z", as_of: "2026-10-19", region: "Assam", status: "complete", git_commit: null, count: 2 },
    withheld: false,
    answers: [recorded("FG01", "filtered_grouped", STARTERS[0], "governed_metric"), recorded("TR01", "trap", "What's the owner's phone number?", "refused")],
  },
  Odisha: { recording: null, answers: [], withheld: false },
};

test("a key is only sent over HTTPS or to this machine", () => {
  expect(keySafe("https://channelpulse-api.onrender.com")).toBe(true);
  expect(keySafe("http://127.0.0.1:8010")).toBe(true);
  expect(keySafe("http://localhost:8000")).toBe(true);
  expect(keySafe("http://api.example.com")).toBe(false);
  expect(keySafe("http://127.0.0.1.example.com")).toBe(false);
});

test.describe("live mode", () => {
  let mode: "live" | "replay" = "live"; // what the stub tells the dashboard server
  let stubDelay = 0; // ms the stub waits before answering status and replay
  const stubCalls: string[] = [];
  let stub: http.Server;
  let server: ChildProcess;

  test.beforeAll(async () => {
    stub = http.createServer((req, res) => {
      const json = { "Content-Type": "application/json" };
      const { pathname } = new URL(req.url ?? "/", "http://stub");
      const replay = REPLAYS[String(req.headers["x-demo-region"])];
      stubCalls.push(req.url ?? "");
      const answer = () => {
        if (pathname === "/api/ask/status") res.writeHead(200, json).end(JSON.stringify(status(mode, FREE)));
        else if (pathname === "/api/ask/replay" && replay) res.writeHead(200, json).end(JSON.stringify(replay));
        else res.writeHead(503, json).end('{"detail":"Not served by the live-mode stub."}');
      };
      if (stubDelay && pathname.startsWith("/api/ask/")) setTimeout(answer, stubDelay);
      else answer();
    });
    await new Promise<void>((resolve) => stub.listen(0, "127.0.0.1", resolve));
    server = spawn(process.execPath, [require.resolve("next/dist/bin/next"), "start", "-p", String(PORT)], {
      cwd: WEB,
      env: { ...process.env, CHANNELPULSE_API_URL: `http://127.0.0.1:${(stub.address() as AddressInfo).port}` },
      stdio: "ignore",
    });
    await expect.poll(async () => (await fetch(`${SITE}/ask`).catch(() => null))?.status ?? 0, { timeout: 30_000 }).toBe(200);
  });
  test.afterAll(async () => {
    server?.kill();
    await new Promise((resolve) => stub?.close(resolve));
  });
  test.afterEach(() => {
    mode = "live";
    stubDelay = 0;
  });

  type Reply = { status: number; body: unknown; headers?: Record<string, string> };

  /**
   * Answers the browser's API calls: the allowance from `free` as it is when the request arrives, and each question
   * with `answer`. `delay` gives the nth status call's wait in ms, or null for never. Returns the requests made.
   */
  async function mockApi(page: Page, answer: () => Reply, free: Free = { ...FREE }, delay: (n: number) => number | null = () => 0) {
    const asked: Request[] = [];
    const statuses: Request[] = [];
    await page.route(/api\.anthropic\.com/, (route) => route.abort());
    await page.route(
      (url) => url.port !== String(PORT) && url.pathname.startsWith("/api/"),
      async (route) => {
        const req = route.request();
        const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Expose-Headers": "Retry-After" };
        const { pathname } = new URL(req.url());
        if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
        if (pathname === "/api/ask/status") {
          statuses.push(req);
          const body = status("live", { ...free });
          const ms = delay(statuses.length);
          if (ms === null) return; // never answers
          if (ms) await new Promise((resolve) => setTimeout(resolve, ms));
          return route.fulfill({ json: body, headers: cors }).catch(() => {}); // the page may have given up or gone
        }
        if (pathname === "/api/ask" && req.method() === "POST") {
          asked.push(req);
          const r = answer();
          return route.fulfill({ status: r.status, json: r.body, headers: { ...cors, ...r.headers } });
        }
        return route.abort();
      },
    );
    return { asked, statuses };
  }

  const answered = (): Reply => ({ status: 200, body: ANSWER });
  const failed = (status: number, code: string, headers?: Record<string, string>): Reply => ({
    status,
    body: { detail: { code, message: `The API's own words for ${code}.` } },
    headers,
  });

  const questionBox = (page: Page) => page.getByRole("textbox", { name: "Your question" });
  const keyField = (page: Page) => page.getByLabel("Your Anthropic API key");
  const allowance = (page: Page) => page.getByTestId("allowance");
  const latest = (page: Page) => page.getByRole("region", { name: "Latest answer" });
  const LEFT = (n: number) => `${n} of 5 free questions left today · Use your own key`;
  const KEY_IN_QUESTION = /That looks like an API key\. Paste it in the key field instead\./;

  async function ask(page: Page, question: string) {
    await questionBox(page).fill(question);
    await page.getByRole("button", { name: "Ask", exact: true }).click();
  }

  async function useKey(page: Page) {
    await page.getByRole("button", { name: "Use your own key" }).click();
    await keyField(page).fill(KEY);
    await page.getByRole("button", { name: "Use key", exact: true }).click();
    await expect(page.getByText("Asking with your key")).toBeVisible();
  }

  test("the ask box leads, then the starter chips and the allowance line; the scored examples start closed", async ({ page }) => {
    await mockApi(page, answered);
    await page.goto(`${SITE}/ask`);
    const line = allowance(page);
    await expect(line).toHaveText(LEFT(3));
    await expect(line).toHaveRole("status"); // a polite live region: its changes are announced
    const chips = page.getByRole("list", { name: "Try one of these" });
    await expect(chips.getByRole("button")).toHaveCount(3);
    const examples = page.locator("details").filter({ has: page.getByText("Scored examples · browse") });
    await expect(examples).not.toHaveAttribute("open");
    const top = async (l: ReturnType<Page["locator"]>) => (await l.boundingBox())!.y;
    const order = [await top(questionBox(page)), await top(chips), await top(line), await top(examples)];
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });

  test("the starter chips are the two governed questions both recorded models answered, and the trap", async ({ page }) => {
    await mockApi(page, answered);
    await page.goto(`${SITE}/ask`);
    await expect(page.getByRole("list", { name: "Try one of these" }).getByRole("button")).toHaveText(STARTERS);
  });

  test("the trap chip fills the box and focuses it, without asking", async ({ page }) => {
    const { asked } = await mockApi(page, answered);
    await page.goto(`${SITE}/ask`);
    await page.getByRole("button", { name: "Try to trip it: What's the owner's phone number?" }).click();
    await expect(questionBox(page)).toHaveValue("What's the owner's phone number?");
    await expect(questionBox(page)).toBeFocused();
    await page.waitForTimeout(500);
    expect(asked).toHaveLength(0);
  });

  test("the page's own status call skips the allowance: the server's address isn't the visitor's", async ({ page }) => {
    await mockApi(page, answered);
    stubCalls.length = 0;
    await page.goto(`${SITE}/ask`);
    const calls = stubCalls.filter((u) => u.startsWith("/api/ask/status"));
    expect(calls.length).toBeGreaterThan(0);
    expect(calls.filter((u) => u !== "/api/ask/status?free=0")).toEqual([]);
  });

  test("the scored examples are fetched alongside the status, so the ask box doesn't wait for both in turn", async ({ page }) => {
    await mockApi(page, answered);
    stubDelay = 2_500;
    const start = Date.now();
    await page.goto(`${SITE}/ask`);
    await expect(questionBox(page)).toBeVisible();
    expect(Date.now() - start).toBeLessThan(4_500); // one wait, not two
  });

  test("a free question carries no key, and the allowance line shows what the API counted", async ({ page }) => {
    const free = { ...FREE };
    const { asked } = await mockApi(page, () => {
      free.remaining = 1; // the API counted this question and one from another tab
      return answered();
    }, free);
    await page.goto(`${SITE}/ask`);
    await expect(allowance(page)).toHaveText(LEFT(3));
    await ask(page, "What's the owner's phone number?");
    await expect(page.getByText(ANSWER.answer_text)).toBeVisible();
    await expect(allowance(page)).toHaveText(LEFT(1));
    expect(asked.map((r) => r.headers()["x-anthropic-key"])).toEqual([undefined]);
  });

  for (const [code, status] of [
    ["server_error", 500],
    ["model_error", 502],
  ] as const) {
    test(`a ${code} still re-counts the allowance: the API counts every owner-paid question`, async ({ page }) => {
      const free = { ...FREE };
      await mockApi(page, () => {
        free.remaining = 2;
        return failed(status, code);
      }, free);
      await page.goto(`${SITE}/ask`);
      await expect(allowance(page)).toHaveText(LEFT(3));
      await ask(page, "What's the owner's phone number?");
      await expect(latest(page)).toContainText(`The API's own words for ${code}.`);
      await expect(allowance(page)).toHaveText(LEFT(2));
    });
  }

  test("a status answer that lands late never overwrites a newer one", async ({ page }) => {
    const free = { ...FREE };
    await mockApi(page, () => {
      free.remaining = 2;
      return answered();
    }, free, (n) => (n === 1 ? 3_000 : 0)); // the mount's call is slow and will say 3 left
    await page.goto(`${SITE}/ask`);
    await ask(page, "What's the owner's phone number?");
    await expect(allowance(page)).toHaveText(LEFT(2), { timeout: 2_500 });
    await page.waitForTimeout(3_500);
    await expect(allowance(page)).toHaveText(LEFT(2));
  });

  test("coming back to the tab re-fetches the allowance: the day may have rolled over", async ({ page }) => {
    const free = { ...FREE };
    await mockApi(page, answered, free);
    await page.goto(`${SITE}/ask`);
    await expect(allowance(page)).toHaveText(LEFT(3));
    free.remaining = 5;
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await expect(allowance(page)).toHaveText(LEFT(5));
  });

  test("the allowance line says it's checking, offers a key meanwhile, and gives up after 8 seconds", async ({ page }) => {
    await mockApi(page, answered, { ...FREE }, () => null);
    await page.goto(`${SITE}/ask`);
    await expect(allowance(page)).toHaveText("Checking free questions… · Use your own key");
    await expect(allowance(page)).toHaveText("Free questions are unavailable right now · Use your own key", { timeout: 12_000 });
  });

  for (const [reason, line] of [
    ["paused", "Free questions are paused right now · Use your own key"],
    ["no_credentials", "Free questions aren't offered here · Use your own key"],
  ] as const) {
    test(`the allowance line when free questions are ${reason}`, async ({ page }) => {
      await mockApi(page, answered, { limit: 5, remaining: 0, available: false, reason });
      await page.goto(`${SITE}/ask`);
      await expect(allowance(page)).toHaveText(line);
    });
  }

  test("used-up free questions change the allowance line, open the key panel, and offer the key instead of a retry", async ({ page }) => {
    const free = { ...FREE };
    await mockApi(
      page,
      () => {
        Object.assign(free, { remaining: 0, available: false, reason: "used" }); // what a re-fetched status says now
        return failed(429, "free_used", { "Retry-After": "3600" });
      },
      free,
    );
    await page.goto(`${SITE}/ask`);
    await expect(allowance(page)).toHaveText(LEFT(3));
    await ask(page, "What's the owner's phone number?");
    await expect(allowance(page)).toHaveText("Today's free questions are used up · Use your own key to keep asking");
    await expect(allowance(page)).not.toContainText(/\d+ of \d+/);
    await expect(keyField(page)).toBeVisible();
    await expect(latest(page).getByRole("button", { name: "Ask again" })).toHaveCount(0);
    await latest(page).getByRole("button", { name: "Use your own key" }).click();
    await expect(keyField(page)).toBeFocused();
    // With a key, asking again makes sense. Retry-After here is hours to midnight UTC: it mustn't hold the button.
    await keyField(page).fill(KEY);
    await page.getByRole("button", { name: "Use key", exact: true }).click();
    await expect(latest(page).getByRole("button", { name: "Ask again" })).toBeEnabled();
  });

  for (const [code, line, paused] of [
    ["free_paused", "Free questions are paused right now · Use your own key", true],
    ["free_unavailable", "Free questions aren't offered here · Use your own key", false],
  ] as const) {
    test(`${code} changes the allowance line, opens the key panel, and offers the key instead of a retry`, async ({ page }) => {
      const free = { ...FREE }; // free_unavailable isn't re-fetched, so a stale status can't undo the line
      const { statuses } = await mockApi(page, () => {
        if (paused) Object.assign(free, { available: false, reason: "paused" });
        return failed(503, code);
      }, free);
      await page.goto(`${SITE}/ask`);
      await expect(allowance(page)).toHaveText(LEFT(3));
      await ask(page, "What's the owner's phone number?");
      await expect(allowance(page)).toHaveText(line);
      await expect(keyField(page)).toBeVisible();
      await expect(latest(page).getByRole("button", { name: "Use your own key" })).toBeVisible();
      await expect(latest(page).getByRole("button", { name: "Ask again" })).toHaveCount(0);
      await page.waitForTimeout(500);
      expect(statuses).toHaveLength(paused ? 2 : 1);
    });
  }

  test("rate_limited holds the retry for Retry-After and leaves the allowance alone", async ({ page }) => {
    const { statuses } = await mockApi(page, () => failed(429, "rate_limited", { "Retry-After": "30" }));
    await page.goto(`${SITE}/ask`);
    await expect(allowance(page)).toHaveText(LEFT(3));
    await ask(page, "What's the owner's phone number?");
    await expect(latest(page)).toContainText("Too many questions from this address");
    await expect(latest(page)).toContainText(/Try again in \d+ seconds\./);
    await expect(latest(page).getByRole("button", { name: "Ask again" })).toBeDisabled();
    await page.waitForTimeout(500);
    expect(statuses).toHaveLength(1);
    await expect(allowance(page)).toHaveText(LEFT(3));
  });

  test("a key typed into the question box is refused before sending, and never kept", async ({ page }) => {
    const { asked } = await mockApi(page, answered);
    await page.goto(`${SITE}/ask`);
    await ask(page, `Use ${KEY} for this`);
    await expect(questionBox(page)).toHaveAccessibleDescription(KEY_IN_QUESTION);
    await expect(keyField(page)).toBeVisible();
    await page.waitForTimeout(500);
    expect(asked).toHaveLength(0);
    expect(await page.evaluate((key) => JSON.stringify({ ...sessionStorage }).includes(key), KEY)).toBe(false);
  });

  test("key_in_question from the API: the question box says why, the key panel opens, and nothing is kept", async ({ page }) => {
    const { statuses } = await mockApi(page, () => failed(400, "key_in_question"));
    await page.goto(`${SITE}/ask`);
    await expect(allowance(page)).toHaveText(LEFT(3));
    const question = "Is sk-ant-short-one my key?";
    await ask(page, question);
    await expect(questionBox(page)).toHaveAccessibleDescription(KEY_IN_QUESTION);
    await expect(keyField(page)).toBeVisible();
    await expect(questionBox(page)).toHaveValue(question); // back in the box to edit, not in the history
    await expect(latest(page)).toHaveCount(0);
    expect(await page.evaluate(() => JSON.stringify({ ...sessionStorage }).includes("sk-ant-short-one"))).toBe(false);
    expect(statuses).toHaveLength(1);
  });

  test("a visitor's key goes only in the request header, and a reload forgets it", async ({ page }) => {
    const { asked } = await mockApi(page, answered);
    await page.goto(`${SITE}/ask`);
    await page.getByRole("button", { name: "Use your own key" }).click();
    await expect(keyField(page)).toHaveAttribute("type", "password");
    await keyField(page).fill(KEY);
    await page.getByRole("button", { name: "Use key", exact: true }).click();
    await expect(page.getByText("Asking with your key")).toBeVisible();
    await ask(page, "What's the owner's phone number?");
    await expect(page.getByText(ANSWER.answer_text)).toBeVisible();
    expect(asked.map((r) => r.headers()["x-anthropic-key"])).toEqual([KEY]);

    const leaks = () =>
      page.evaluate(
        (key) => [JSON.stringify({ ...localStorage }), JSON.stringify({ ...sessionStorage }), document.cookie, location.href].filter((s) => s.includes(key)),
        KEY,
      );
    expect(await leaks()).toEqual([]);

    await page.reload();
    await expect(page.getByText(ANSWER.answer_text)).toBeVisible(); // the history survives the reload; the key doesn't
    await expect(allowance(page)).toHaveText(LEFT(3)); // the key's answer spent no free question
    expect(await leaks()).toEqual([]);
    await ask(page, "What's the owner's phone number?");
    await expect.poll(() => asked.length).toBe(2);
    expect(asked[1].headers()["x-anthropic-key"]).toBeUndefined();
  });

  test("Forget key drops the key at once: the next question goes without it", async ({ page }) => {
    const { asked } = await mockApi(page, answered);
    await page.goto(`${SITE}/ask`);
    await useKey(page);
    await ask(page, "What's the owner's phone number?");
    await expect.poll(() => asked.length).toBe(1);
    await page.getByRole("button", { name: "Forget key" }).click();
    await expect(allowance(page)).toHaveText(LEFT(3));
    await ask(page, "What's the owner's phone number?");
    await expect.poll(() => asked.length).toBe(2);
    expect(asked.map((r) => r.headers()["x-anthropic-key"])).toEqual([KEY, undefined]);
  });

  test("opening the key panel puts focus in the key field", async ({ page }) => {
    await mockApi(page, answered);
    await page.goto(`${SITE}/ask`);
    await page.getByRole("button", { name: "Use your own key" }).click();
    await expect(keyField(page)).toBeFocused();
  });

  test("the key field isn't in a form a browser offers to save, and Enter applies the key", async ({ page }) => {
    await mockApi(page, answered);
    await page.goto(`${SITE}/ask`);
    await page.getByRole("button", { name: "Use your own key" }).click();
    const field = keyField(page);
    await expect(field).toHaveAttribute("type", "password");
    expect(await field.evaluate((el) => el.closest("form") === null)).toBe(true);
    for (const [name, value] of [
      ["data-1p-ignore", ""],
      ["data-lpignore", "true"],
      ["data-bwignore", ""],
      ["data-form-type", "other"],
    ]) {
      await expect(field).toHaveAttribute(name, value);
    }
    await expect(page.getByText("If your browser offers to save it, choose Never.", { exact: false })).toBeVisible();
    await field.fill(KEY);
    await field.press("Enter");
    await expect(allowance(page)).toHaveText("Asking with your key · free questions untouched · Forget key");
  });

  test("a key in the wrong format is refused under the field, and nothing is sent with it", async ({ page }) => {
    const { asked } = await mockApi(page, answered);
    await page.goto(`${SITE}/ask`);
    await page.getByRole("button", { name: "Use your own key" }).click();
    // A zero-width space, and a non-breaking hyphen for the dash: both come along with a copy from a document.
    for (const bad of [KEY.replace("api03", "api​03"), KEY.replace("sk-ant-", "sk‑ant-")]) {
      await keyField(page).fill(bad);
      await page.getByRole("button", { name: "Use key", exact: true }).click();
      await expect(keyField(page)).toHaveAccessibleDescription(/That doesn't look like an Anthropic key\. They start with sk-ant-\./);
      await expect(keyField(page)).toBeFocused(); // back on the field to fix
    }
    await expect(allowance(page)).toHaveText(LEFT(3));
    await ask(page, "What's the owner's phone number?");
    await expect(page.getByText(ANSWER.answer_text)).toBeVisible();
    expect(asked.map((r) => r.headers()["x-anthropic-key"])).toEqual([undefined]);
  });

  test("the key panel closes from inside, with or without a key, and an unapplied draft goes with it", async ({ page }) => {
    await mockApi(page, () => failed(401, "key_rejected"));
    await page.goto(`${SITE}/ask`);
    await page.getByRole("button", { name: "Use your own key" }).click();
    await keyField(page).fill("sk-ant-a-draft-never-applied-0123456789");
    await page.getByRole("button", { name: "Close key panel" }).click();
    await expect(keyField(page)).toHaveCount(0);
    await page.getByRole("button", { name: "Use your own key" }).click();
    await expect(keyField(page)).toHaveValue("");
    // A key error reopens the panel with the key still set: it still closes, and Forget key stays in reach.
    await keyField(page).fill(KEY);
    await page.getByRole("button", { name: "Use key", exact: true }).click();
    await ask(page, "What's the owner's phone number?");
    await expect(keyField(page)).toBeVisible();
    await page.getByRole("button", { name: "Close key panel" }).click();
    await expect(keyField(page)).toHaveCount(0);
    await expect(allowance(page).getByRole("button", { name: "Forget key" })).toBeVisible();
  });

  for (const [code, status, message] of [
    ["key_invalid", 400, "That doesn't look like an Anthropic key. They start with sk-ant-."],
    ["key_rejected", 401, "Anthropic didn't accept that key. Check it, or make a new one."],
    ["key_limited", 402, "Your key hit an Anthropic rate or spend limit."],
  ] as const) {
    test(`${code} tells the visitor what's wrong with their key, under the key field`, async ({ page }) => {
      await mockApi(page, () => failed(status, code));
      await page.goto(`${SITE}/ask`);
      await useKey(page);
      await ask(page, "What's the owner's phone number?");
      await expect(keyField(page)).toBeVisible();
      await expect(keyField(page)).toHaveAccessibleDescription(new RegExp(message.replace(/\./g, "\\.")));
    });
  }

  test("the scorecard counts up when the examples are first opened, not while they're closed", async ({ page }) => {
    await mockApi(page, answered);
    await page.goto(`${SITE}/ask?region=Assam`);
    await page.waitForTimeout(1_500); // longer than a count-up: one that ran while closed has finished
    const examples = page.locator("details").filter({ has: page.getByText("Scored examples · browse") });
    await examples.evaluate((el) => {
      const w = window as unknown as { __frames: string[] };
      w.__frames = [];
      new MutationObserver((records) => {
        for (const r of records) {
          const fig = (r.target instanceof Element ? r.target : r.target.parentElement)?.closest("[data-final]");
          if (fig && r.type === "characterData") w.__frames.push(fig.textContent ?? "");
        }
      }).observe(el, { subtree: true, childList: true, characterData: true });
    });
    await page.getByText("Scored examples · browse").click();
    await expect(page.locator("[data-final]")).toHaveCount(3);
    await page.waitForTimeout(1_500);
    expect(await page.evaluate(() => (window as unknown as { __frames: string[] }).__frames.length), "the figures counted after opening").toBeGreaterThan(3);
    await expect(examples.locator("[data-final] [data-digits]")).toHaveText(["2", "1", "1"]); // settled on the exact values
  });

  test("with no recording yet, the examples' notice doesn't describe replay mode", async ({ page }) => {
    await mockApi(page, answered);
    await page.goto(`${SITE}/ask?region=Odisha`);
    await page.getByText("Scored examples · browse").click();
    const notice = page.getByRole("region", { name: "Scored answers from the evaluation run" });
    await expect(notice).toBeVisible();
    await expect(notice).not.toContainText("Replay mode");
  });

  test("the page sends a CSP that limits connections to the API's origin and forbids framing", async ({ page }) => {
    const violations: string[] = [];
    page.on("console", (m) => {
      if (/Content Security Policy/i.test(m.text())) violations.push(m.text());
    });
    await mockApi(page, answered);
    const statusCall = page.waitForRequest((r) => r.url().endsWith("/api/ask/status"));
    const res = (await page.goto(`${SITE}/ask`))!;
    const apiOrigin = new URL((await statusCall).url()).origin;
    const headers = res.headers();
    expect(headers["content-security-policy"]).toContain(`connect-src 'self' ${apiOrigin};`);
    expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["referrer-policy"]).toBe("no-referrer");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["strict-transport-security"]).toBe("max-age=63072000; includeSubDomains");
    await useKey(page);
    await ask(page, "What's the owner's phone number?");
    await expect(page.getByText(ANSWER.answer_text)).toBeVisible();
    expect(violations).toEqual([]);
  });

  test("live_off from the API falls back to the replay view", async ({ page }) => {
    await mockApi(page, () => {
      mode = "replay"; // the owner switched live mode off
      return failed(503, "live_off");
    });
    await page.goto(`${SITE}/ask`);
    await ask(page, "What's the owner's phone number?");
    await expect(questionBox(page)).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Recorded answers" })).toBeVisible(); // the stub has no recording to replay
  });

  // Next 15.5 sometimes never applies a refresh (D53), and CI caught this fallback stuck on the ask box for good.
  test("live_off falls back to the replay view even when Next never applies a refresh", async ({ page }) => {
    await mockApi(page, () => {
      mode = "replay";
      return failed(503, "live_off");
    });
    await page.goto(`${SITE}/ask`);
    await page.route(/[?&]_rsc=/, () => {}); // every server-component fetch from now on stalls
    await ask(page, "What's the owner's phone number?");
    await expect(questionBox(page)).toHaveCount(0, { timeout: 15_000 });
    await expect(page.getByRole("region", { name: "Recorded answers" })).toBeVisible();
  });
});
