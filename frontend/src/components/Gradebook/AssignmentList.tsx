"use client";
import React from "react";
import type { GradedAssignment, GradeCategory } from "@/lib/types";

interface Props {
  assignments: GradedAssignment[];
  categories: GradeCategory[];
  onAdd: () => void;
  onEditGrade: (id: string, pointsEarned: number | null) => void;
  onEditFull: (a: GradedAssignment) => void;
  onSyncGradescope: () => void;
}

export function AssignmentList({
  assignments, categories, onAdd, onEditGrade, onEditFull, onSyncGradescope,
}: Props) {
  const catName = (id: string | null) =>
    categories.find((c) => c.id === id)?.name ?? "Uncategorized";

  return (
    <section
      style={{
        border: "1px solid var(--border)", borderRadius: 8,
        padding: 16, background: "var(--bg)",
      }}
    >
      <header
        style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "baseline", marginBottom: 12,
        }}
      >
        <div className="label-micro">Assignments</div>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" onClick={onAdd}
            style={{
              fontSize: 12, padding: "4px 10px", border: "1px solid var(--border)",
              borderRadius: 6, background: "var(--bg)", cursor: "pointer",
            }}>
            + Add
          </button>
          <button type="button" onClick={onSyncGradescope} disabled
            title="Coming soon"
            style={{
              fontSize: 12, padding: "4px 10px", border: "1px solid var(--border)",
              borderRadius: 6, background: "var(--bg-soft)", color: "var(--text-dim)",
              cursor: "not-allowed",
            }}>
            Sync Gradescope
          </button>
        </div>
      </header>
      {assignments.length === 0 ? (
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          No assignments yet.
        </p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {assignments.map((a) => (
            <li key={a.id}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "8px 0", borderBottom: "1px dashed var(--border)",
              }}>
              <button type="button" onClick={() => onEditFull(a)}
                style={{
                  flex: 1, textAlign: "left", background: "none",
                  border: 0, padding: 0, cursor: "pointer", color: "var(--text)",
                }}>
                <div style={{ fontWeight: 500 }}>{a.title}</div>
                <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                  {catName(a.category_id)}
                  {a.due_date ? ` · due ${a.due_date}` : ""}
                </div>
              </button>
              <input
                type="number"
                placeholder="—"
                defaultValue={a.points_earned ?? ""}
                onBlur={(e) => {
                  const v = e.target.value === "" ? null : Number(e.target.value);
                  if (v !== a.points_earned) onEditGrade(a.id, v);
                }}
                style={{
                  width: 60, padding: 4, textAlign: "right",
                  border: "1px solid var(--border)", borderRadius: 4,
                }}
              />
              <span style={{ color: "var(--text-dim)", fontSize: 12 }}>
                / {a.points_possible ?? "—"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
