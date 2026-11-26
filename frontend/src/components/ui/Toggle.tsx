"use client";
import React from "react";
import { cn } from "@/lib/cn";

// Shared segmented control (the ONE pill-shaped toggle). Replaces the ad-hoc
// mode/model toggles. Pill shape is correct here — it signals "pick one of these",
// distinct from a rectangular action <Button>.
export function Toggle<T extends string>({
  options,
  value,
  onChange,
  size = "md",
  testid,
  labelledBy,
}: {
  options: { value: T; label: React.ReactNode; title?: string }[];
  value: T;
  onChange: (v: T) => void;
  size?: "sm" | "md";
  /** Container testid; each option gets `${testid}-${value}`. */
  testid?: string;
  /** The id of the row's visible label: the row is then a group named by it,
   *  so a screen reader says what the pressed option is a choice of. */
  labelledBy?: string;
}) {
  const pad = size === "sm" ? "5px 12px" : "7px 15px";
  const fs = size === "sm" ? 12 : 13;
  return (
    <div
      data-testid={testid}
      role={labelledBy ? "group" : undefined}
      aria-labelledby={labelledBy}
      className="inline-flex bg-bg-soft rounded-[var(--r-full)] p-[3px] gap-0.5 flex-wrap"
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
            className={cn("rounded-[var(--r-full)] border-0 cursor-pointer [transition:all_var(--dur-fast)_var(--ease)] font-sans", on ? "font-semibold" : "font-medium", on ? "bg-brand-forest" : "bg-transparent", on ? "text-accent-fg" : "text-text-dim")} style={{ padding: pad, fontSize: fs }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
