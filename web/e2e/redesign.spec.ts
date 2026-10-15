import { expect, test, type Page } from "@playwright/test";

// The Monsoon Editorial system (web/DESIGN.md): themes, contrast, fonts and motion.

const TEXT = ["--text", "--text-muted", "--text-subtle", "--accent", "--adhoc", "--danger", "--good", "--marigold"];
const SURFACES = ["--canvas", "--surface-sunken", "--surface", "--surface-raised", "--surface-hover"];

async function themeOf(page: Page) {
  return page.locator("html").getAttribute("data-theme");
}

test("opens in the dark theme, and a light choice survives reloads", async ({ page }) => {
  await page.goto("/");
  expect(await themeOf(page)).toBe("dark");
  await page.getByRole("button", { name: "Switch to the light theme" }).click();
  expect(await themeOf(page)).toBe("light");
  await page.reload();
  expect(await themeOf(page)).toBe("light"); // set before paint by the inline script, no click needed
  await page.goto("/quality");
  expect(await themeOf(page)).toBe("light");
  await page.getByRole("button", { name: "Switch to the dark theme" }).click();
  expect(await themeOf(page)).toBe("dark");
});

for (const theme of ["dark", "light"] as const) {
  test(`every text token clears WCAG AA on every surface (${theme})`, async ({ page }) => {
    await page.goto("/");
    const failures = await page.evaluate(
      ({ theme, text, surfaces }) => {
        document.documentElement.dataset.theme = theme;
        const css = getComputedStyle(document.documentElement);
        const rgb = (name: string) => {
          // The production build minifies #ffffff to #fff: expand short hex before reading channels.
          const raw = css.getPropertyValue(name).trim();
          const hex = raw.length === 4 ? `#${[...raw.slice(1)].map((c) => c + c).join("")}` : raw;
          return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
        };
        const lum = (c: number[]) => {
          const [r, g, b] = c.map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
          return 0.2126 * r + 0.7152 * g + 0.0722 * b;
        };
        const ratio = (a: string, b: string) => {
          const [hi, lo] = [lum(rgb(a)), lum(rgb(b))].sort((x, y) => y - x);
          return (hi + 0.05) / (lo + 0.05);
        };
        return text.flatMap((t) => surfaces.filter((s) => !(ratio(t, s) >= 4.5)).map((s) => `${t} on ${s}: ${ratio(t, s).toFixed(2)}`));
      },
      { theme, text: TEXT, surfaces: SURFACES },
    );
    expect(failures).toEqual([]);
  });
}

test("the three families load, and the title and KPI figures are set in the display serif", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
  const loaded = await page.evaluate(async () => {
    await document.fonts.ready;
    return [...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family);
  });
  for (const family of ["Newsreader", "Plus Jakarta Sans", "JetBrains Mono"]) {
    expect(loaded.some((f) => f.includes(family)), `${family} loaded`).toBe(true);
  }
  const titleFont = await page.locator("h1").first().evaluate((el) => getComputedStyle(el).fontFamily);
  expect(titleFont).toContain("Newsreader");
  const figureFont = await page.locator("[data-figure]").first().evaluate((el) => getComputedStyle(el).fontFamily);
  expect(figureFont).toContain("Newsreader");
});

test.describe("with reduced motion", () => {
  test.use({ reducedMotion: "reduce" });
  test("nothing animates and figures show their final value at once", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
    const running = await page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length);
    expect(running).toBe(0);
    for (const fig of await page.locator("[data-final]").all()) {
      expect((await fig.innerText()).replace(/\s/g, "")).toContain((await fig.getAttribute("data-final"))!.replace(/\s/g, ""));
    }
  });
});

test("KPI figures count up and settle on exactly the formatted value", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
  const figures = page.locator("[data-final]");
  await expect(figures).toHaveCount(5);
  await page.waitForTimeout(1500); // the count-up runs 900 ms
  for (const fig of await figures.all()) {
    expect((await fig.innerText()).replace(/\s/g, "")).toContain((await fig.getAttribute("data-final"))!.replace(/\s/g, ""));
  }
});

test("a counting figure never shows a sign its value doesn't have", async ({ page }) => {
  // Record every text a counting figure shows, from the first frame on (polling would miss the earliest frames).
  await page.addInitScript(() => {
    const w = window as unknown as { __frames: string[] };
    w.__frames = [];
    new MutationObserver((records) => {
      for (const r of records) {
        const fig = (r.target instanceof Element ? r.target : r.target.parentElement)?.closest("[data-final]");
        if (fig && !/^[−-]/.test(fig.getAttribute("data-final") ?? "")) w.__frames.push(fig.textContent ?? "");
      }
    }).observe(document, { subtree: true, childList: true, characterData: true });
  });
  await page.goto("/");
  await expect(page.locator("[data-final]")).toHaveCount(5);
  await page.waitForTimeout(1500);
  const frames = await page.evaluate(() => (window as unknown as { __frames: string[] }).__frames);
  expect(frames.length, "the figures counted").toBeGreaterThan(5);
  expect(frames.filter((f) => /[−-]\d/.test(f))).toEqual([]);
});

test("the header carries the aurora and the canvas the grain, and neither takes a click", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("header .cp-aurora")).toHaveCount(1);
  await expect(page.locator(".cp-grain")).toHaveCount(1);
  const toggle = page.getByRole("button", { name: /Switch to the (light|dark) theme/ });
  const box = (await toggle.boundingBox())!;
  const hit = await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.closest("button")?.getAttribute("aria-label") ?? null, [box.x + box.width / 2, box.y + box.height / 2]);
  expect(hit).toMatch(/Switch to the (light|dark) theme/);
});

// The sparkline stroke doesn't scale with its stretched viewBox, so a dash-based draw-in measured its dashes on
// screen and left gaps in the line for good. Sparklines reveal with a wipe instead and keep a solid stroke.
test("sparklines land as whole lines, without dash gaps", async ({ page }) => {
  await page.goto("/");
  const lines = page.locator('section[aria-labelledby="kpi-heading"] svg path[stroke="var(--series-1)"]');
  await expect(lines).toHaveCount(5);
  await page.waitForTimeout(2500);
  expect(await lines.evaluateAll((els) => els.map((e) => getComputedStyle(e).strokeDasharray))).toEqual(Array(5).fill("none"));
});

test("charts draw in when their data changes, not when the window resizes", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
  const sales = page.locator('section[aria-labelledby="sales"] .cp-plot svg');
  await expect(sales).toHaveClass(/cp-enter/);
  // Plot draws rounded bars as paths and square ones as rects: every bar grows, whichever element draws it.
  const grows = await sales.locator('g[aria-label="rect"]:not([fill^="url("]) > *').evaluateAll((bars) => bars.map((b) => getComputedStyle(b).animationName));
  expect(grows.length).toBeGreaterThan(0);
  expect([...new Set(grows)]).toEqual(["cp-grow"]);
  await page.evaluate(() => document.querySelectorAll(".cp-enter").forEach((s) => s.classList.remove("cp-enter")));
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.waitForTimeout(500);
  await expect(page.locator('section[aria-labelledby="sales"] .cp-plot svg.cp-enter')).toHaveCount(0);
  await page.getByRole("button", { name: /^Date range/ }).click();
  await page.getByRole("group", { name: "Presets" }).getByRole("button").nth(1).click();
  await expect(page.locator('section[aria-labelledby="sales"] .cp-plot svg.cp-enter')).toHaveCount(1);
});
