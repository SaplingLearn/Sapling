"use client";
import React from "react";
import { Pill } from "../Pill";

// Shared wrapping filter-group control (family "b"): a row of selectable pills
// that wraps to multiple lines. Use for "All" + N dynamic filters (categories,
// topics, tiers). For a fixed, connected segmented control (2–5 options), use
// <Toggle> instead. Per-option `color` tints the active pill (e.g. mastery tiers);
// per-option `icon` renders leading content (e.g. a colored dot).
export function FilterPills<T extends string>({
  options,
  value,
  onChange,
  gap = 6,
  className,
  style,
}: {
  options: { value: T; label: React.ReactNode; color?: string; icon?: React.ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  gap?: number;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className={className}
      style={{ display: "flex", gap, flexWrap: "wrap", ...style }}
    >
      {options.map((o) => (
        <Pill
          key={o.value}
          active={o.value === value}
          onClick={() => onChange(o.value)}
          color={o.color}
          icon={o.icon}
        >
          {o.label}
        </Pill>
      ))}
    </div>
  );
}
