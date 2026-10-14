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
