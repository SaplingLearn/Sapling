"use client";
import React from "react";
import { cn } from "@/lib/cn";

export function Pill({
  children,
  active,
  onClick,
  icon,
  color,
  testId,
  size = "sm",
}: {
  children: React.ReactNode;
  active?: boolean;
  onClick?: () => void;
  icon?: React.ReactNode;
  color?: string;
  testId?: string;
  /** `sm` (default) is the filter-row pill everywhere else; `md` sits beside
   *  body-size text, as quiz home's course pills do. */
  size?: "sm" | "md";
}) {
  const md = size === "md";
  return (
    <button
      data-testid={testId}
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn("inline-flex items-center gap-1.5 rounded-[var(--r-full)] [transition:all_var(--dur-fast)_var(--ease)] font-sans", md ? "py-[7px] px-[15px]" : "py-[5px] px-[11px]", md ? "text-base" : "text-sm")} style={{ background: active ? (color || "var(--accent-soft)") : "transparent", color: active ? (color ? "#fff" : "var(--accent)") : "var(--text-dim)", border: `1px solid ${active ? (color || "var(--accent-border)") : "var(--border)"}` }}
    >
      {icon}
      {children}
    </button>
  );
}
