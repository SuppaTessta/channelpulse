"use client";

import { useEffect, useRef, useState } from "react";

const NUMBER = /^([−+-]?)(\d[\d,]*(?:\.\d+)?)$/;
const parse = (digits: string) => Number(digits.replace(/,/g, ""));
/** Same decimals and the same grouping as the formatted value (Indian lakh grouping when it had commas). */
function format(v: number, like: string): string {
  const decimals = like.split(".")[1]?.length ?? 0;
  return like.includes(",")
    ? v.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    : v.toFixed(decimals);
}
const easeOutExpo = (t: number) => (t >= 1 ? 1 : 1 - 2 ** (-10 * t));

/**
 * Digits that count up to their value on first show, and from the old value to the new one on a change. The
 * server renders the final text and the last frame restores it exactly; reduced motion shows it at once.
 */
export function CountUp({ value, duration = 900 }: { value: string; duration?: number }) {
  const [shown, setShown] = useState(value);
  const last = useRef<number | null>(null);
  useEffect(() => {
    const m = NUMBER.exec(value);
    const target = m ? parse(m[2]) : null;
    if (!m || target == null || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setShown(value);
      last.current = target;
      return;
    }
    const [, sign, digits] = m;
    const from = last.current ?? 0;
    last.current = target;
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      // A frame's timestamp can precede `start` (it marks when the frame began): clamp, or the first frame dips below zero.
      const t = Math.max(0, Math.min(1, (now - start) / duration));
      setShown(t >= 1 ? value : sign + format(from + (target - from) * easeOutExpo(t), digits));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);
  return <>{shown}</>;
}
