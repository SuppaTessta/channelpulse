import { expect, test, type Page } from "@playwright/test";

// The Monsoon Editorial system (web/DESIGN.md): themes, contrast, fonts and motion.

const TEXT = ["--text", "--text-muted", "--text-subtle", "--accent", "--adhoc", "--danger", "--good", "--marigold"];
const SURFACES = ["--canvas", "--surface-sunken", "--surface", "--surface-raised", "--surface-hover"];

async function themeOf(page: Page) {
  return page.locator("html").getAttribute("data-theme");
}

/**
 * Clicks a theme toggle until the page shows `to`. A click right after a load can land before hydration, and the switch
 * commits a frame later inside a view transition, so one click and one read raced on CI. A repeated click is harmless:
 * the toggle reads the current theme at click time.
 */
async function switchTheme(page: Page, to: "light" | "dark", toggle = page.getByRole("button", { name: `Switch to the ${to} theme` })) {
  await expect(async () => {
    if ((await themeOf(page)) !== to) await toggle.click({ timeout: 2_000 });
    await expect(page.locator("html")).toHaveAttribute("data-theme", to, { timeout: 1_000 });
  }).toPass({ timeout: 15_000 });
}

test("opens in the dark theme, and a light choice survives reloads", async ({ page }) => {
  await page.goto("/");
  expect(await themeOf(page)).toBe("dark");
  await switchTheme(page, "light");
  await page.reload();
  expect(await themeOf(page)).toBe("light"); // set before paint by the inline script, no click needed
  await page.goto("/quality");
  expect(await themeOf(page)).toBe("light");
  await switchTheme(page, "dark");
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
  await expect(toggle).toBeVisible(); // boundingBox() doesn't wait
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

// A dollar figure (the traces' estimated cost) is a figure like any rupee one, not muted as if it had no value.
test("the trace totals set every value as a figure, the dollar cost included", async ({ page }) => {
  await page.goto("/traces");
  const totals = page.locator("section[aria-labelledby=trace-totals]");
  await expect(totals.getByText("Estimated cost")).toBeVisible();
  await expect(totals.locator("[data-figure]")).toHaveCount(4);
});

// The draw-in traces solid lines only: a pathLength of 1 on the dashed provisional segment stretched its 4px dash
// over the whole line, so provisional periods lost their dashes (final review #2).
test("dashed provisional lines stay dashed after the draw-in", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".cp-plot svg.cp-enter").first()).toBeVisible();
  const dashed = page.locator('.cp-plot g[aria-label="line"][stroke-dasharray] path');
  await expect(dashed.first()).toBeAttached();
  expect(await dashed.evaluateAll((ps) => ps.map((p) => p.getAttribute("pathLength")))).toEqual(Array(await dashed.count()).fill(null));
});

// Neighbouring footnote markers must not cover each other's hit areas: clicking "1" opened Source 2 (final review #3).
test("a footnote marker opens its own source", async ({ page }) => {
  await page.goto("/brief");
  const first = page.getByRole("button", { name: /^Source 1:/ });
  await expect(first).toBeVisible();
  const box = (await first.boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.getByRole("dialog")).toContainText("Source 1");
  await expect(page.getByRole("dialog")).not.toContainText("Source 2");
});

// Keyboard focus scrolled into view must land below the sticky header, which grew to two rows below 1280px (review #4).
for (const width of [768, 1024, 1440]) {
  test(`scroll padding clears the sticky header at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/distributors/D0001");
    // boundingBox() doesn't wait: on a slow runner it read the header before the page settled and got null (CI).
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
    await expect(page.locator("header").first()).toBeVisible();
    const header = await page.locator("header").first().boundingBox();
    const padding = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop));
    expect(padding).toBeGreaterThanOrEqual(header!.height);
  });
}

// Leftovers from the final review (decisions D54 follow-up).
test.describe("leftovers", () => {
  test("every theme toggle agrees after a switch, whatever the width", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await switchTheme(page, "light", page.getByRole("button", { name: "Switch to the light theme" }).filter({ visible: true }));
    await page.setViewportSize({ width: 1024, height: 900 });
    const rail = page.getByRole("button", { name: /Switch to the (light|dark) theme/ }).filter({ visible: true });
    await expect(rail).toHaveAccessibleName("Switch to the dark theme");
    await rail.click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  });

  test("a remembered light choice sets the browser chrome colour on load", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("cp-theme", "light"));
    await page.goto("/");
    // Every theme-color tag: Next renders the viewport's one, and the stream can add another.
    expect(await page.locator('meta[name="theme-color"]').evaluateAll((ms) => [...new Set(ms.map((m) => m.getAttribute("content")))])).toEqual(["#f6f3ec"]);
  });

  test("printing from dark drops the chart glow", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('.cp-plot g[aria-label="line"]').first()).toBeAttached();
    await page.emulateMedia({ media: "print" });
    await page.waitForTimeout(800); // print layout is narrower: let the charts redraw at its width first
    const filters = await page.locator('.cp-plot g[aria-label="line"]').evaluateAll((gs) => [...new Set(gs.map((g) => getComputedStyle(g).filter))]);
    expect(filters).toEqual(["none"]);
  });

  test("backdrop blur only on the header, drawers and popovers", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
    const blur = (sel: string) => page.locator(sel).first().evaluate((e) => getComputedStyle(e).backdropFilter);
    expect(await blur("button[aria-label^='Date range']")).toBe("none");
    expect(await blur("[role=combobox]")).toBe("none");
    expect(await blur("header .rounded-panel")).toBe("none");
    expect(await blur("header")).not.toBe("none");
  });

  test("endless loops animate only transform and opacity", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(3000);
    const props = await page.evaluate(() =>
      [...new Set(document.getAnimations()
        .filter((a) => a.effect?.getTiming().iterations === Infinity)
        .flatMap((a) => (a.effect as KeyframeEffect).getKeyframes().flatMap((k) => Object.keys(k)))
        .filter((k) => !["offset", "easing", "composite", "computedOffset"].includes(k)))],
    );
    expect(props.length).toBeGreaterThan(0);
    expect(props.filter((p) => p !== "transform" && p !== "opacity")).toEqual([]);
  });

  test("the header and filter row rise with the page, 40ms apart", async ({ page }) => {
    await page.goto("/");
    expect(await page.locator("header > div.relative").first().evaluate((e) => getComputedStyle(e).animationName)).toBe("cp-rise");
    expect(await page.locator("header + div > div").first().evaluate((e) => getComputedStyle(e).animationDelay)).toBe("0.04s");
    const delays = await page.locator("section[aria-labelledby=kpi-heading] .cp-stagger").evaluate((s) => [...s.children].slice(0, 3).map((c) => getComputedStyle(c).animationDelay));
    expect(delays).toEqual(["0s", "0.04s", "0.08s"]);
  });

  test("the marigold glow is a token", async ({ page }) => {
    await page.goto("/");
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--glow-marigold").trim())).not.toBe("");
  });

  test("the scrollbar gutter is reserved, so a late scrollbar doesn't redraw the charts", async ({ page }) => {
    await page.goto("/");
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).scrollbarGutter)).toBe("stable");
  });

  for (const width of [390, 1024, 1440]) {
    test(`the loading header is the height of the real one at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");
      await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
      // Hold the next page's data back so the loading state stays up long enough to measure.
      await page.route(/\/distributors\?.*_rsc=|\/distributors\?_rsc=/, async (route) => {
        await new Promise((r) => setTimeout(r, 2500));
        await route.continue().catch(() => {});
      });
      if (width < 768) {
        await page.getByRole("button", { name: "Open page menu" }).click();
        await page.getByRole("dialog").getByRole("link", { name: "Distributor 360" }).click();
      } else {
        await page.getByRole("navigation", { name: "Pages" }).locator('a[href^="/distributors"]').first().click();
      }
      const skeleton = page.locator('div[aria-busy="true"] > div.border-b').first();
      await expect(skeleton).toBeVisible();
      const loading = (await skeleton.boundingBox())!.height;
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Distributor 360", { timeout: 30_000 });
      const real = (await page.locator("header").first().boundingBox())!.height;
      expect(Math.abs(loading - real), `loading ${loading}px vs header ${real}px`).toBeLessThanOrEqual(8);
    });
  }

  test("figures settle on exactly the formatted digits, before and after a filter change", async ({ page }) => {
    await page.goto("/");
    const digits = page.locator("section[aria-labelledby=kpi-heading] [data-figure] [data-digits]");
    await expect(digits).toHaveCount(5);
    const settle = async () => {
      await page.waitForTimeout(1500);
      return page.locator("section[aria-labelledby=kpi-heading] [data-figure]").evaluateAll((els) => els.map((e) => [e.getAttribute("data-final"), e.querySelector("[data-digits]")?.textContent]));
    };
    const before = await settle();
    for (const [final, shown] of before) expect(shown).toBe(final);
    await page.getByRole("button", { name: /^Date range/ }).click();
    await page.getByRole("group", { name: "Presets" }).getByRole("button").nth(1).click();
    await expect(page.locator("section[aria-labelledby=kpi-heading] [data-figure]").first()).not.toHaveAttribute("data-final", before[0][0]!, { timeout: 60_000 });
    const after = await settle();
    for (const [final, shown] of after) expect(shown).toBe(final);
  });
});
