"use client";
import React from "react";

// Shared segmented control (the ONE pill-shaped toggle). Replaces the ad-hoc
// mode/model toggles. Pill shape is correct here — it signals "pick one of these",
// distinct from a rectangular action <Button>.
export function Toggle<T extends string>({
  options,
  value,
  onChange,
  size = "md",
  testid,
}: {
  options: { value: T; label: React.ReactNode; title?: string }[];
  value: T;
  onChange: (v: T) => void;
  size?: "sm" | "md";
  /** Container testid; each option gets `${testid}-${value}`. */
  testid?: string;
}) {
  const pad = size === "sm" ? "5px 12px" : "7px 15px";
  const fs = size === "sm" ? 12 : 13;
  return (
    <div
      data-testid={testid}
      style={{
        display: "inline-flex",
        background: "var(--bg-soft)",
        borderRadius: "var(--r-full)",
        padding: 3,
        gap: 2,
        flexWrap: "wrap",
      }}
    >
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            title={o.title}
            aria-pressed={on}
            data-testid={testid ? `${testid}-${o.value}` : undefined}
            style={{
              padding: pad,
              fontSize: fs,
              fontWeight: on ? 600 : 500,
              borderRadius: "var(--r-full)",
              border: 0,
              cursor: "pointer",
              background: on ? "var(--brand-forest)" : "transparent",
              color: on ? "#fff" : "var(--text-dim)",
              transition: "all var(--dur-fast) var(--ease)",
              fontFamily: "var(--font-sans)",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
