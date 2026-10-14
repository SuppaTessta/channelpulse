"use client";

import { Moon, Sun } from "@phosphor-icons/react";
import { useEffect, useState, type MouseEvent } from "react";
import { flushSync } from "react-dom";
import { cx, ICON } from "./ui";

type Theme = "dark" | "light";
/** The browser chrome colour per edition (each edition's canvas). */
const CHROME: Record<Theme, string> = { dark: "#070b14", light: "#f6f3ec" };
export const THEME_KEY = "cp-theme";

/** Runs in <head> before first paint, so a remembered light choice never flashes dark (layout.tsx). */
export const THEME_SCRIPT = `try{document.documentElement.dataset.theme=localStorage.getItem("${THEME_KEY}")==="light"?"light":"dark"}catch(e){}`;

function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", CHROME[theme]);
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    // Storage blocked (private mode): the choice lasts for this page only.
  }
}

/** Switches between the dark (Monsoon) and light (paper) editions; the new one is revealed from the button. */
export function ThemeToggle({ variant }: { variant: "rail" | "sidebar" | "sheet" }) {
  const [theme, setTheme] = useState<Theme>("dark");
  useEffect(() => setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark"), []);
  const next: Theme = theme === "dark" ? "light" : "dark";

  function toggle(e: MouseEvent<HTMLButtonElement>) {
    const commit = () => {
      apply(next);
      setTheme(next);
    };
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !document.startViewTransition) return commit();
    const r = e.currentTarget.getBoundingClientRect();
    document.documentElement.style.setProperty("--vt-x", `${r.left + r.width / 2}px`);
    document.documentElement.style.setProperty("--vt-y", `${r.top + r.height / 2}px`);
    document.startViewTransition(() => flushSync(commit));
  }

  const Icon = next === "light" ? Sun : Moon;
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to the ${next} theme`}
      title={`Switch to the ${next} theme`}
      className={cx(
        "flex items-center gap-2.5 rounded-control text-muted transition-colors duration-200 hover:bg-hover hover:text-ink",
        variant === "rail" && "mx-auto size-10 justify-center",
        variant === "sidebar" && "mx-3 h-9 px-2.5 text-[13px] font-medium",
        variant === "sheet" && "h-12 px-3 text-[15px] font-medium",
      )}
    >
      <Icon size={20} {...ICON} aria-hidden />
      {variant === "rail" ? null : <span>{next === "light" ? "Light theme" : "Dark theme"}</span>}
    </button>
  );
}
