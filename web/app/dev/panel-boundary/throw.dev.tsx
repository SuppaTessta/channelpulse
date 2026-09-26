"use client";

export function ThrowOnRender(): never {
  throw new Error("fixture: a client component failed");
}
