"use client";

/**
 * The course field used at the top of the Study pages (the hub, Flashcards):
 * a button showing the chosen course, and a menu of the student's courses
 * exactly as wide as it.
 *
 * Every course's row is laid in the same cell of the field and only the chosen
 * one is shown, so the field is as wide as the LONGEST row. That is what lets
 * the menu match the field's width without cutting a name short, and it stops
 * the field (and the header beside it) changing width with each pick.
 *
 * Keyboard and screen reader (spec §13 A135, the same pattern as CustomSelect):
 * Enter, Space or an arrow key opens the list, which takes focus with the
 * chosen course active (its `aria-activedescendant`). Up / Down move, Home /
 * End jump, Enter or Space picks, Escape closes; both hand focus back to the
 * field. Tab closes and moves on; a click outside closes.
 */
import React, { useId, useLayoutEffect, useRef, useState } from "react";
import { Icon } from "../Icon";
import type { EnrolledCourse } from "@/lib/api";
import s from "./CoursePicker.module.css";

/** `value` for the "every course" row, when the picker offers one. */
export const ALL_COURSES = "all";

type Row = { id: string; color: string | null; code: string; name: string | null; meta: string | null };

function RowContent({ row, withMeta }: { row: Row; withMeta: "show" | "reserve" }) {
  return (
    <>
      <span style={{ width: 9, height: 9, borderRadius: "50%", background: row.color || "var(--text-muted)", flexShrink: 0 }} />
      {/* Code and name are ONE line box, not two flex items. They are
          different faces at different sizes (mono 14 over sans 13), so
          centring a box each left them on baselines ~1px apart; as inline
          children of one span they share the line's baseline by construction.
          The ellipsis moves here with them. */}
      <span style={{ flex: withMeta === "show" ? 1 : undefined, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        <span style={{ fontSize: "var(--fs-base)", fontWeight: 600 }}>{row.code}</span>
        {row.name && <span style={{ marginLeft: 8, fontSize: "var(--fs-md)", fontWeight: 400, color: "var(--text-dim)" }}>{row.name}</span>}
      </span>
      {row.meta && (
        // In the field this only RESERVES the room the menu's row needs.
        <span aria-hidden={withMeta === "reserve" || undefined} style={{ visibility: withMeta === "reserve" ? "hidden" : undefined, paddingLeft: 8, flexShrink: 0, fontSize: "var(--fs-xs)", fontWeight: 400, color: "var(--text-muted)", whiteSpace: "nowrap" }}>{row.meta}</span>
      )}
    </>
  );
}

/** The listbox's key handling: a new active index, or a pick / close. */
type ListKey = { move: number } | { pick: true } | { close: "refocus" | "moveOn" } | null;

export function listKey(key: string, active: number, count: number): ListKey {
  switch (key) {
    case "ArrowDown": return { move: Math.min(count - 1, active + 1) };
    case "ArrowUp": return { move: Math.max(0, active - 1) };
    case "Home": return { move: 0 };
    case "End": return { move: count - 1 };
    case "Enter":
    case " ": return { pick: true };
    case "Escape": return { close: "refocus" };
    case "Tab": return { close: "moveOn" };
    default: return null;
  }
}

function courseRows(courses: EnrolledCourse[], allLabel?: string,
                    meta?: (course: EnrolledCourse) => string | null): Row[] {
  return [
    ...(allLabel ? [{ id: ALL_COURSES, color: null, code: allLabel, name: null, meta: null }] : []),
    ...courses.map(c => ({
      id: c.course_id, color: c.color, code: c.course_code || c.course_name,
      name: c.course_code ? c.course_name : null, meta: meta ? meta(c) : null,
    })),
  ];
}

export function CoursePicker({
  courses,
  value,
  onChange,
  allLabel,
  meta,
  fullWidth = false,
}: {
  courses: EnrolledCourse[];
  /** A course id, or `ALL_COURSES` when `allLabel` is given. */
  value: string;
  onChange: (courseId: string) => void;
  /** Adds a first "every course" row with this label (value `ALL_COURSES`). */
  allLabel?: string;
  /** A short note at the end of a course's menu row, e.g. "2 upcoming". */
  meta?: (course: EnrolledCourse) => string | null;
  /** Take the whole row (phones), so the menu still matches the field. */
  fullWidth?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const fieldRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const baseId = useId();
  const optionId = (i: number) => `${baseId}-opt-${i}`;
  const rows = courseRows(courses, allLabel, meta);
  const chosenIndex = Math.max(0, rows.findIndex(r => r.id === value));
  const chosen = rows[chosenIndex];

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) fieldRef.current?.focus();
  };
  const openList = () => { setActive(chosenIndex); setOpen(true); };
  const pick = (i: number) => {
    const row = rows[i];
    close(true);
    if (row) onChange(row.id);
  };

  // The open list takes focus once, and keeps its active row in view.
  useLayoutEffect(() => { if (open) listRef.current?.focus({ preventScroll: true }); }, [open]);
  useLayoutEffect(() => {
    if (open) document.getElementById(optionId(active))?.scrollIntoView?.({ block: "nearest" });
    // optionId is derived from the stable useId value
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, active]);

  const onFieldKey = (e: React.KeyboardEvent) => {
    if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(e.key)) {
      e.preventDefault();
      if (open) close(false);
      else openList();
    }
  };
  const onListKey = (e: React.KeyboardEvent) => {
    const step = listKey(e.key, active, rows.length);
    if (!step) return;
    if ("close" in step) {
      if (step.close === "refocus") { e.preventDefault(); e.stopPropagation(); }
      close(step.close === "refocus");
      return;
    }
    e.preventDefault();
    if ("pick" in step) pick(active);
    else setActive(step.move);
  };

  const fieldName = chosen ? `Course, ${[chosen.code, chosen.name].filter(Boolean).join(" ")}` : "Course";

  return (
    <div style={{ position: "relative", flex: fullWidth ? "1 1 100%" : "0 1 auto", minWidth: 0, maxWidth: 560 }}>
      <button ref={fieldRef} type="button" className={`btn ${s.field}`} onClick={() => (open ? close(false) : openList())}
        onKeyDown={onFieldKey} aria-haspopup="listbox" aria-expanded={open} aria-label={fieldName}
        style={fullWidth ? { width: "100%" } : undefined}>
        <span style={{ display: "grid", minWidth: 0 }}>
          {rows.map(row => {
            const shown = row.id === chosen?.id;
            return (
              <span key={row.id} aria-hidden={shown ? undefined : true} style={{ gridArea: "1 / 1", visibility: shown ? "visible" : "hidden", display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                <RowContent row={row} withMeta="reserve" />
              </span>
            );
          })}
        </span>
        <span aria-hidden="true" className={s.chevron}><Icon name="chevron-down" size={10} /></span>
      </button>
      {open && (
        <>
          <div onClick={() => close(false)} style={{ position: "fixed", inset: 0, zIndex: 30 }} />
          <div ref={listRef} role="listbox" aria-label="Courses" tabIndex={-1} className={s.menu}
            aria-activedescendant={optionId(active)} onKeyDown={onListKey}>
            {rows.map((row, i) => {
              const on = row.id === chosen?.id;
              return (
                <div key={row.id} id={optionId(i)} role="option" aria-selected={on}
                  data-active={i === active || undefined} className={s.option}
                  onMouseEnter={() => setActive(i)} onClick={() => pick(i)}>
                  <RowContent row={row} withMeta="show" />
                  {/* The tick sits where the field's chevron does. */}
                  <span aria-hidden="true" style={{ marginLeft: "auto", width: 10, display: "grid", justifyItems: "center", flexShrink: 0, color: "var(--brand-forest)" }}>{on && <Icon name="check" size={12} />}</span>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
