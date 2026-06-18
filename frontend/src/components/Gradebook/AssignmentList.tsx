"use client";
import React from "react";
import type { GradedAssignment, GradeCategory } from "@/lib/types";
import { categoryColor } from "@/components/Gradebook/categoryColor";

interface Props {
  assignments: GradedAssignment[];
  /** When curve mode is active, the curved versions of assignments (same IDs,
   * curved points_earned). Displayed as an overlay next to the raw score. */
  curvedAssignments?: GradedAssignment[];
  categories: GradeCategory[];
  /** Assignment IDs currently excluded from their category's grade by a
   * drop-lowest policy. Used to visually mute the row + show a chip. */
  droppedIds?: Set<string>;
  onAdd: () => void;
  onEditGrade: (id: string, pointsEarned: number | null) => void;
  onEditFull: (a: GradedAssignment) => void;
  onSyncGradescope?: () => void;
  /** Opens the Gradescope setup/settings modal regardless of ready state. */
  onGradescopeSettings?: () => void;
  /** When true, the sync button performs a one-click sync. */
  gradescopeReady?: boolean;
  /** When true, the sync button shows a syncing state. */
  gradescopeBusy?: boolean;
  /** ISO timestamp of the last successful sync for this course. */
  gradescopeLastSyncedAt?: string | null;
  highlightedCategory?: string | null;
}

export function AssignmentList({
  assignments,
  curvedAssignments,
  categories,
  droppedIds,
  onAdd,
  onEditGrade,
  onEditFull,
  onSyncGradescope,
  onGradescopeSettings,
  gradescopeReady,
  gradescopeBusy,
  gradescopeLastSyncedAt,
  highlightedCategory,
}: Props) {
  const dropped = droppedIds ?? new Set<string>();
  const sortedCats = React.useMemo(
    () => [...categories].sort((a, b) => a.sort_order - b.sort_order),
    [categories],
  );

  const curvedById = React.useMemo(() => {
    if (!curvedAssignments) return new Map<string, GradedAssignment>();
    return new Map(curvedAssignments.map((a) => [a.id, a]));
  }, [curvedAssignments]);

  const grouped = React.useMemo(() => {
    const map = new Map<string | null, GradedAssignment[]>();
    for (const a of assignments) {
      const list = map.get(a.category_id) ?? [];
      list.push(a);
      map.set(a.category_id, list);
    }
    // Most recent due date first, nulls last.
    for (const [, list] of map) {
      list.sort((a, b) => {
        if (a.due_date && b.due_date) return b.due_date.localeCompare(a.due_date);
        if (a.due_date) return -1;
        if (b.due_date) return 1;
        return a.title.localeCompare(b.title);
      });
    }
    return map;
  }, [assignments]);

  const uncategorized = grouped.get(null) ?? [];
  const hasAny = assignments.length > 0;

  return (
    <section>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 28,
          gap: 16,
          paddingBottom: 14,
          borderBottom: "1px solid var(--border)",
        }}
      >
        <h2
          style={{
            fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
            fontWeight: 500,
            fontSize: 22,
            lineHeight: 1.15,
            letterSpacing: "-0.01em",
            color: "var(--text)",
            margin: 0,
          }}
        >
          Assignments
        </h2>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          {onSyncGradescope && (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
              <button
                type="button"
                onClick={onSyncGradescope}
                disabled={gradescopeBusy}
                className="btn"
                style={{
                  padding: "8px 14px",
                  fontSize: 13,
                  opacity: gradescopeBusy ? 0.7 : 1,
                  cursor: gradescopeBusy ? "wait" : "pointer",
                }}
                title={
                  gradescopeReady
                    ? "Pull latest grades from your linked Gradescope course"
                    : "Connect Gradescope and pick the matching course"
                }
              >
                {gradescopeBusy
                  ? "Syncing…"
                  : gradescopeReady
                    ? "Sync from Gradescope"
                    : "Set Up Gradescope Sync"}
              </button>
              {(gradescopeLastSyncedAt || onGradescopeSettings) && (
                <div
                  className="mono"
                  style={{
                    fontSize: 10,
                    color: "var(--text-muted)",
                    letterSpacing: "-0.01em",
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                  }}
                >
                  {gradescopeLastSyncedAt && (
                    <span title={new Date(gradescopeLastSyncedAt).toLocaleString()}>
                      Synced {timeAgo(gradescopeLastSyncedAt)}
                    </span>
                  )}
                  {onGradescopeSettings && (
                    <button
                      type="button"
                      onClick={onGradescopeSettings}
                      style={{
                        background: "none",
                        border: 0,
                        padding: 0,
                        margin: 0,
                        font: "inherit",
                        color: "var(--text-dim)",
                        textDecoration: "underline",
                        textUnderlineOffset: 3,
                        textDecorationColor: "var(--border-strong)",
                        cursor: "pointer",
                      }}
                    >
                      Settings
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
          <button
            type="button"
            onClick={onAdd}
            className="btn btn--primary"
            style={{ padding: "8px 14px", fontSize: 13 }}
          >
            + Add Assignment
          </button>
        </div>
      </div>

      {!hasAny ? (
        <EmptyEntries onAdd={onAdd} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 44 }}>
          {sortedCats.map((cat) => {
            const items = grouped.get(cat.id) ?? [];
            if (items.length === 0) return null;
            return (
              <CategoryGroup
                key={cat.id}
                id={`category-${cat.id}`}
                title={cat.name}
                color={categoryColor(cat.name)}
                items={items}
                dropLowest={cat.drop_lowest ?? 0}
                droppedIds={dropped}
                curvedById={curvedById}
                onEditGrade={onEditGrade}
                onEditFull={onEditFull}
                highlighted={highlightedCategory === cat.id}
              />
            );
          })}
          {uncategorized.length > 0 && (
            <CategoryGroup
              id="category-uncategorized"
              title="Uncategorized"
              color="var(--text-muted)"
              items={uncategorized}
              dropLowest={0}
              droppedIds={dropped}
              curvedById={curvedById}
              onEditGrade={onEditGrade}
              onEditFull={onEditFull}
              highlighted={false}
            />
          )}
        </div>
      )}
    </section>
  );
}

function CategoryGroup({
  id,
  title,
  color,
  items,
  dropLowest,
  droppedIds,
  curvedById,
  onEditGrade,
  onEditFull,
  highlighted,
}: {
  id: string;
  title: string;
  color: string;
  items: GradedAssignment[];
  dropLowest: number;
  droppedIds: Set<string>;
  curvedById: Map<string, GradedAssignment>;
  onEditGrade: (id: string, pointsEarned: number | null) => void;
  onEditFull: (a: GradedAssignment) => void;
  highlighted: boolean;
}) {
  // Group-level summary: how many graded out of total
  const graded = items.filter((a) => a.points_earned !== null).length;
  const droppedCount = items.filter((a) => droppedIds.has(a.id)).length;

  return (
    <div
      id={id}
      style={{
        scrollMarginTop: 16,
        background: highlighted
          ? "color-mix(in oklab, var(--accent) 9%, transparent)"
          : "transparent",
        borderRadius: "var(--r-md)",
        transition: "background-color var(--dur-slow) var(--ease)",
        padding: "8px 12px",
        margin: "-8px -12px",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 14,
          flexWrap: "wrap",
        }}
      >
        <span
          className="mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--text-dim)",
            fontWeight: 600,
          }}
        >
          {title}
        </span>
        <span
          className="mono"
          style={{
            fontSize: 11,
            color: "var(--text-muted)",
            letterSpacing: "-0.01em",
          }}
        >
          {graded}/{items.length}
        </span>
        {dropLowest > 0 && (
          <span
            className="mono"
            title={`Drops the ${dropLowest} lowest graded assignment${dropLowest === 1 ? "" : "s"}. ${droppedCount}/${dropLowest} dropped so far.`}
            style={{
              fontSize: 10,
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              color: "var(--accent)",
              background: "var(--accent-soft)",
              border: "1px solid var(--accent-border)",
              borderRadius: "var(--r-full)",
              padding: "2px 8px",
              fontWeight: 600,
              lineHeight: 1.4,
            }}
          >
            drops {droppedCount}/{dropLowest}
          </span>
        )}
      </div>
      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: "0 0 0 20px",
          borderLeft: `2px solid ${color}`,
          display: "flex",
          flexDirection: "column",
        }}
      >
        {items.map((a) => {
          const isDropped = droppedIds.has(a.id);
          const curved = curvedById.get(a.id);
          const hasCurvedScore =
            curved != null &&
            curved.points_earned !== null &&
            curved.points_earned !== a.points_earned;
          return (
            <li
              key={a.id}
              className="assignment-row"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "14px 8px",
                borderBottom: "1px solid var(--border)",
                borderRadius: 6,
                margin: "0 -8px",
              }}
            >
              <button
                type="button"
                onClick={() => onEditFull(a)}
                style={{
                  flex: 1,
                  minWidth: 0,
                  textAlign: "left",
                  background: "none",
                  border: 0,
                  padding: 0,
                  cursor: "pointer",
                  color: "var(--text)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    gap: 8,
                    minWidth: 0,
                  }}
                >
                  <span
                    style={{
                      fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
                      fontWeight: 500,
                      fontSize: 15,
                      color: isDropped ? "var(--text-muted)" : "var(--text)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      textDecoration: isDropped ? "line-through" : "none",
                      textDecorationColor: "var(--text-muted)",
                      textDecorationThickness: 1,
                    }}
                  >
                    {a.title}
                  </span>
                  {isDropped && (
                    <span
                      className="mono"
                      title="This is currently your lowest score in the category and is excluded from the average."
                      style={{
                        fontSize: 9,
                        letterSpacing: "0.08em",
                        textTransform: "uppercase",
                        color: "var(--accent)",
                        background: "var(--accent-soft)",
                        border: "1px solid var(--accent-border)",
                        borderRadius: "var(--r-full)",
                        padding: "1px 6px",
                        fontWeight: 600,
                        flexShrink: 0,
                      }}
                    >
                      dropped
                    </span>
                  )}
                </div>
                <div
                  className="mono"
                  style={{
                    fontSize: 11,
                    color: "var(--text-dim)",
                    marginTop: 3,
                    letterSpacing: "-0.01em",
                  }}
                >
                  {a.due_date ? `Due ${a.due_date.slice(5, 7)}/${a.due_date.slice(8, 10)}/${a.due_date.slice(0, 4)}` : "No Due Date"}
                </div>
              </button>
              <input
                type="number"
                placeholder="—"
                defaultValue={a.points_earned ?? ""}
                min={0}
                step="any"
                onBlur={(e) => {
                  const v = e.target.value === "" ? null : Number(e.target.value);
                  if (Number.isNaN(v as number)) return;
                  if (v !== a.points_earned) onEditGrade(a.id, v);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                }}
                aria-label={`Points earned for ${a.title}`}
                title={
                  a.points_possible !== null
                    ? `0–${a.points_possible} pts (extra credit allowed)`
                    : "Points earned"
                }
                className="assignment-grade-input"
                style={{ opacity: isDropped ? 0.4 : 1 }}
              />
              <span
                className="mono"
                style={{
                  fontSize: 13,
                  color: "var(--text-muted)",
                  minWidth: 40,
                  textAlign: "left",
                  opacity: isDropped ? 0.4 : 1,
                }}
              >
                / {a.points_possible ?? "—"}
              </span>
              {hasCurvedScore && curved && (
                <span
                  className="mono"
                  title="Curved score"
                  style={{
                    fontSize: 12,
                    color: "var(--accent)",
                    whiteSpace: "nowrap",
                    opacity: isDropped ? 0.4 : 1,
                  }}
                >
                  → {curved.points_earned!.toFixed(1)}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function EmptyEntries({ onAdd }: { onAdd: () => void }) {
  return (
    <div style={{ padding: "48px 0", maxWidth: 560 }}>
      <h3
        style={{
          fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
          fontWeight: 500,
          fontSize: 28,
          lineHeight: 1.1,
          margin: "0 0 12px",
          color: "var(--text)",
          letterSpacing: "-0.01em",
        }}
      >
        Nothing entered yet.
      </h3>
      <p
        style={{
          fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
          fontSize: 16,
          lineHeight: 1.6,
          color: "var(--text-dim)",
          margin: "0 0 24px",
        }}
      >
        Add an assignment by hand, or upload your syllabus from the Gradebook
        page to populate this list automatically.
      </p>
      <button
        type="button"
        className="btn btn--primary"
        onClick={onAdd}
        style={{ padding: "10px 18px", fontSize: 14 }}
      >
        + Add an assignment
      </button>
    </div>
  );
}

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "just now";
  const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}
