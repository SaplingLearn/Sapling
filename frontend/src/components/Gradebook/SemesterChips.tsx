"use client";
import React from "react";

interface Props {
  semesters: string[];
  selected: string;
  onSelect: (semester: string) => void;
}

const CHIP_TRANSITION =
  "background-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease)";

export function SemesterChips({ semesters, selected, onSelect }: Props) {
  return (
    <div
      role="tablist"
      aria-label="Semester"
      style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}
    >
      {semesters.map((s) => {
        const active = s === selected;
        return (
          <button
            key={s}
            type="button"
            role="tab"
            aria-current={active ? "true" : undefined}
            aria-selected={active}
            onClick={() => onSelect(s)}
            style={{
              padding: "4px 12px",
              borderRadius: "var(--r-full)",
              border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
              background: active ? "var(--accent)" : "var(--bg)",
              color: active ? "var(--accent-fg)" : "var(--text)",
              fontSize: 12,
              fontWeight: active ? 600 : 400,
              cursor: "pointer",
              transition: CHIP_TRANSITION,
            }}
          >
            {s}
          </button>
        );
      })}
    </div>
  );
}
