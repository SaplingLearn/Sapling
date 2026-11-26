"use client";
import React from "react";
import type { GradedAssignment, GradeCategory } from "@/lib/types";
import { categoryColor } from "@/components/Gradebook/categoryColor";
import { now } from "@/lib/testMode";
import { cn } from "@/lib/cn";

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
  const [hoveredTab, setHoveredTab] = React.useState<string | null>(null);

  return (
    <section>
      <div
        className="flex justify-between items-baseline mb-7 gap-4 pb-3.5 border-b border-b-border"
      >
        <h2
          className="font-display font-medium text-2xl leading-[1.15] tracking-[-0.01em] text-text m-0"
        >
          Assignments
        </h2>
        <div className="flex gap-2.5 items-center flex-wrap">
          {onSyncGradescope && (
            <div className="flex flex-col items-end gap-0.5">
              <button
                type="button"
                onClick={onSyncGradescope}
                disabled={gradescopeBusy}
                className={cn("btn", "py-2 px-3.5 text-md", gradescopeBusy ? "opacity-70" : "opacity-100", gradescopeBusy ? "cursor-wait" : "cursor-pointer")}
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
                  className="mono text-2xs text-text-muted tracking-[-0.01em] flex gap-2 items-center"
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
                      className="[background:none] border-0 p-0 m-0 [font:inherit] text-text-dim underline [text-underline-offset:3px] decoration-border-strong cursor-pointer"
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
            data-testid="gradebook-add-assignment"
            onClick={onAdd}
            className="btn btn--primary py-2 px-3.5 text-md"
          >
            + Add Assignment
          </button>
        </div>
      </div>

      {hasAny && (
        <div
          className="flex gap-1.5 flex-wrap mb-7"
        >
          {sortedCats.map((cat) => {
            const items = grouped.get(cat.id) ?? [];
            if (items.length === 0) return null;
            const isActive = highlightedCategory === cat.id;
            return (
              <button
                key={cat.id}
                type="button"
                onClick={() => {
                  const el = document.getElementById(`category-${cat.id}`);
                  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
                onMouseEnter={() => setHoveredTab(cat.id)}
                onMouseLeave={() => setHoveredTab(null)}
                className={cn("py-[5px] px-3.5 rounded-[var(--r-full)] text-sm font-sans cursor-pointer [transition:border-color_0.12s,_background_0.12s,_color_0.12s] whitespace-nowrap", isActive ? "font-semibold" : "font-normal")} style={{ border: `1.5px solid ${isActive ? categoryColor(cat.name) : hoveredTab === cat.id ? "var(--border-strong)" : "var(--border)"}`, background: isActive
                    ? `color-mix(in oklch, ${categoryColor(cat.name)}, transparent 85%)`
                    : hoveredTab === cat.id ? "var(--bg-subtle)" : "var(--bg)", color: isActive ? categoryColor(cat.name) : hoveredTab === cat.id ? "var(--text)" : "var(--text-dim)" }}
              >
                {cat.name}
                <span
                  className="mono text-2xs text-text-muted ml-[5px]"
                >
                  {items.length}
                </span>
              </button>
            );
          })}
          {uncategorized.length > 0 && (
            <button
              type="button"
              onClick={() => {
                const el = document.getElementById("category-uncategorized");
                if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
              onMouseEnter={() => setHoveredTab("__uncategorized__")}
              onMouseLeave={() => setHoveredTab(null)}
              className={cn(cn("py-[5px] px-3.5 rounded-[var(--r-full)] text-sm font-sans cursor-pointer [transition:border-color_0.12s,_background_0.12s,_color_0.12s] whitespace-nowrap", hoveredTab === "__uncategorized__" ? "bg-bg-subtle" : "bg-bg", hoveredTab === "__uncategorized__" ? "text-text" : "text-text-dim"), hoveredTab === "__uncategorized__" ? "border-[1.5px] border-border-strong" : "border-[1.5px] border-border")}
            >
              Uncategorized
              <span className="mono text-2xs text-text-muted ml-[5px]">
                {uncategorized.length}
              </span>
            </button>
          )}
        </div>
      )}

      {!hasAny ? (
        <EmptyEntries onAdd={onAdd} />
      ) : (
        <div className="flex flex-col gap-11">
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
      className={cn("[scroll-margin-top:16px] rounded-md [transition:background-color_var(--dur-slow)_var(--ease)] py-2 px-3 -my-2 -mx-3", highlighted ? "bg-[color-mix(in_oklab,_var(--accent)_9%,_transparent)]" : "bg-transparent")}
    >
      <div
        className="flex items-center gap-3 mb-3.5 flex-wrap"
      >
        <span
          aria-hidden="true"
          className="w-2 h-2 rounded-[50%] shrink-0" style={{ background: color }}
        />
        <span
          className="mono text-md text-text-dim font-semibold"
        >
          {title}
        </span>
        <span
          className="mono text-xs text-text-muted tracking-[-0.01em]"
        >
          {graded}/{items.length}
        </span>
        {dropLowest > 0 && (
          <span
            className="mono text-sm text-accent bg-accent-soft border border-accent-border rounded-[var(--r-full)] py-0.5 px-2 font-semibold leading-[1.4]"
            title={`Drops the ${dropLowest} lowest graded assignment${dropLowest === 1 ? "" : "s"}. ${droppedCount}/${dropLowest} dropped so far.`}
          >
            {dropLowest} Drops
          </span>
        )}
      </div>
      <ul
        className="list-none m-0 pt-0 pr-0 pb-0 pl-5 border-l border-l-border flex flex-col"
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
              className="assignment-row flex items-center gap-3 py-3.5 px-3 my-0 -mx-3 rounded-sm relative"
            >
              <button
                type="button"
                onClick={() => onEditFull(a)}
                className="flex-1 min-w-0 text-left [background:none] border-0 p-0 cursor-pointer text-text"
              >
                <div
                  className="flex items-center gap-2 min-w-0 overflow-hidden"
                >
                  <span
                    className={cn("font-serif font-medium text-[15px] decoration-text-muted [text-decoration-thickness:1px] text-ellipsis whitespace-nowrap min-w-0 shrink", isDropped ? "text-text-muted" : "text-text", isDropped ? "line-through" : "no-underline")}
                  >
                    {a.title}
                  </span>
                  {isDropped && (
                    <span
                      className="chip chip--accent shrink-0"
                      title="This is currently your lowest score in the category and is excluded from the average."
                    >
                      Dropped
                    </span>
                  )}
                  {hasCurvedScore && (
                    <span
                      className="mono shrink-0 text-xs text-c-sky bg-[color-mix(in_oklch,_var(--c-sky),_transparent_88%)] border border-[color-mix(in_oklch,_var(--c-sky),_transparent_70%)] rounded-[var(--r-full)] py-0.5 px-2 font-semibold"
                      title="Bell curve has been applied to this assignment's score."
                    >
                      Curved
                    </span>
                  )}
                </div>
                <div
                  className="mono text-xs text-text-dim mt-[3px] tracking-[-0.01em]"
                >
                  {a.due_date ? `Due ${a.due_date.slice(5, 7)}/${a.due_date.slice(8, 10)}/${a.due_date.slice(0, 4)}` : "No Due Date"}
                </div>
              </button>
              <div className="flex items-center gap-0.5 shrink-0">
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
                  className={cn("assignment-grade-input", isDropped ? "opacity-40" : "opacity-100")}
                />
                <span className={cn("mono", "text-md text-text-muted", isDropped ? "opacity-40" : "opacity-100")}>/</span>
                <span className={cn("mono", "text-md text-text-muted whitespace-nowrap", isDropped ? "opacity-40" : "opacity-100")}>
                  {a.points_possible ?? "—"}
                </span>
                {hasCurvedScore && curved && (
                  <span
                    className={cn("mono", "text-sm text-accent whitespace-nowrap ml-1", isDropped ? "opacity-40" : "opacity-100")}
                    title="Curved score"
                  >
                    → {curved.points_earned!.toFixed(1)}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function EmptyEntries({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="py-12 px-0 max-w-140">
      <h3
        className="font-display font-medium text-[28px] leading-[1.1] mt-0 mx-0 mb-3 text-text tracking-[-0.01em]"
      >
        Nothing entered yet.
      </h3>
      <p
        className="font-serif text-lg leading-[1.6] text-text-dim mt-0 mx-0 mb-6"
      >
        Add an assignment by hand, or upload your syllabus from the Gradebook
        page to populate this list automatically.
      </p>
      <button
        type="button"
        className="btn btn--primary py-2.5 px-4.5 text-base"
        onClick={onAdd}
      >
        + Add an assignment
      </button>
    </div>
  );
}

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "just now";
  // now() = the test-mode clock (frozen under NEXT_PUBLIC_TEST_MODE, #426),
  // Date.now() otherwise — keeps the "Synced Xm ago" label deterministic in e2e.
  const diffSec = Math.max(0, Math.floor((now() - then) / 1000));
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}
