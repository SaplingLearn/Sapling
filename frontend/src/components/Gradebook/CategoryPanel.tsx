"use client";
import React from "react";
import type { GradeCategory } from "@/lib/types";

interface Props {
  categories: GradeCategory[];
  onEdit: () => void;
}

export function CategoryPanel({ categories, onEdit }: Props) {
  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: 16,
        marginBottom: 16,
        background: "var(--bg)",
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 8,
        }}
      >
        <div className="label-micro">Categories</div>
        <button
          type="button"
          onClick={onEdit}
          style={{
            fontSize: 12,
            padding: "4px 10px",
            border: "1px solid var(--border)",
            borderRadius: 6,
            background: "var(--bg)",
            cursor: "pointer",
          }}
        >
          Edit weights
        </button>
      </header>
      {categories.length === 0 ? (
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          No categories yet. Click &quot;Edit weights&quot; to add some, or upload a syllabus.
        </p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {categories.map((c) => (
            <li
              key={c.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                padding: "6px 0",
                borderBottom: "1px dashed var(--border)",
              }}
            >
              <span>
                {c.name} <span style={{ color: "var(--text-dim)" }}>({c.weight}%)</span>
              </span>
              <span style={{ fontWeight: 500 }}>
                {c.category_grade != null
                  ? `${(c.category_grade * 100).toFixed(1)}%`
                  : "—"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
