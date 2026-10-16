"use client";

import { useLayoutEffect, useRef } from "react";

const NUMBER = /^([−+-]?)(\d[\d,]*(?:\.\d+)?)$/;
const isMinus = (sign: string) => sign === "−" || sign === "-";
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
 * server renders the final text, frames are written straight to the text node (no re-render per frame), and the
 * last frame restores the exact text; reduced motion shows it at once. A new unit or currency remounts it (Figure
 * keys it), so it never counts lakh into crore.
 */
export function CountUp({ value, duration = 900 }: { value: string; duration?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const last = useRef<number | null>(null);
  useLayoutEffect(() => {
    const node = ref.current?.firstChild;
    const m = NUMBER.exec(value);
    if (!node || !m) return;
    const [, sign, digits] = m;
    const target = (isMinus(sign) ? -1 : 1) * Number(digits.replace(/,/g, ""));
    const from = last.current ?? 0;
    last.current = target;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      node.nodeValue = value;
      return;
    }
    const write = (v: number) => {
      // The value's own sign when it has one; a minus while counting through negatives towards a positive value.
      node.nodeValue = (v < 0 ? (isMinus(sign) ? sign : "−") : sign && !isMinus(sign) ? sign : "") + format(Math.abs(v), digits);
    };
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      // A frame's timestamp can precede `start` (it marks when the frame began): clamp, or the first frame dips below zero.
      const t = Math.max(0, Math.min(1, (now - start) / duration));
      if (t >= 1) node.nodeValue = value;
      else write(from + (target - from) * easeOutExpo(t));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    write(from);
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);
  return (
    <span ref={ref} data-digits="">
      {value}
    </span>
  );
}
