"use client";
import React from "react";

interface Props {
  semesters: string[];
  selected: string;
  onSelect: (semester: string) => void;
}

export function SemesterChips({ semesters, selected, onSelect }: Props) {
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
      {semesters.map((s) => {
        const active = s === selected;
        return (
          <button
            key={s}
            type="button"
            onClick={() => onSelect(s)}
            style={{
              padding: "4px 12px",
              borderRadius: 999,
              border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
              background: active ? "var(--accent)" : "var(--bg)",
              color: active ? "#fff" : "var(--text)",
              fontSize: 12,
              fontWeight: active ? 600 : 400,
              cursor: "pointer",
              transition: "all var(--dur-fast) var(--ease)",
            }}
          >
            {s}
          </button>
        );
      })}
    </div>
  );
}
