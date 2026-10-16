"use client";

import { Moon, Sun } from "@phosphor-icons/react";
import { useEffect, useSyncExternalStore, type MouseEvent } from "react";
import { flushSync } from "react-dom";
import { cx, ICON } from "./ui";

type Theme = "dark" | "light";
/** The browser chrome colour per edition (each edition's canvas). */
const CHROME: Record<Theme, string> = { dark: "#070b14", light: "#f6f3ec" };
export const THEME_KEY = "cp-theme";

/**
 * Runs in <head> before first paint, so a remembered light choice never flashes dark (layout.tsx). It sets the
 * browser chrome colour too, which the server always renders dark.
 */
export const THEME_SCRIPT = `try{var t=localStorage.getItem("${THEME_KEY}")==="light"?"light":"dark";document.documentElement.dataset.theme=t;if(t==="light")document.addEventListener("DOMContentLoaded",function(){document.querySelectorAll('meta[name="theme-color"]').forEach(function(m){m.setAttribute("content","${CHROME.light}")})})}catch(e){}`;

function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", CHROME[theme]));
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    // Storage blocked (private mode): the choice lasts for this page only.
  }
}

// The page's own attribute is the one source of truth, so the rail, sidebar and sheet toggles always agree.
const current = (): Theme => (document.documentElement.dataset.theme === "light" ? "light" : "dark");
function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

/** Switches between the dark (Monsoon) and light (paper) editions; the new one is revealed from the button. */
export function ThemeToggle({ variant }: { variant: "rail" | "sidebar" | "sheet" }) {
  const theme = useSyncExternalStore(subscribe, current, () => "dark" as Theme);
  // The server renders the chrome colour dark, and streaming can add a second tag after the head script ran.
  useEffect(() => document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", CHROME[current()])), []);
  const next: Theme = theme === "dark" ? "light" : "dark";

  function toggle(e: MouseEvent<HTMLButtonElement>) {
    const target: Theme = current() === "dark" ? "light" : "dark"; // read at click time, never a stale render
    const commit = () => apply(target);
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
