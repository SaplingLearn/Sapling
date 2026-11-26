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
 */
import React from "react";
import { Icon } from "../Icon";
import type { EnrolledCourse } from "@/lib/api";
import s from "./CoursePicker.module.css";
import { cn } from "@/lib/cn";

/** `value` for the "every course" row, when the picker offers one. */
export const ALL_COURSES = "all";

type Row = { id: string; color: string | null; code: string; name: string | null; meta: string | null };

function RowContent({ row, withMeta }: { row: Row; withMeta: "show" | "reserve" }) {
  return (
    <>
      <span className="w-[9px] h-[9px] rounded-[50%] shrink-0" style={{ background: row.color || "var(--text-muted)" }} />
      {/* Code and name are ONE line box, not two flex items. They are
          different faces at different sizes (mono 14 over sans 13), so
          centring a box each left them on baselines ~1px apart; as inline
          children of one span they share the line's baseline by construction.
          The ellipsis moves here with them. */}
      <span className={cn("min-w-0 whitespace-nowrap overflow-hidden text-ellipsis", withMeta === "show" ? "flex-1" : "")}>
        <span className="text-base font-semibold">{row.code}</span>
        {row.name && <span className="ml-2 text-md font-normal text-text-dim">{row.name}</span>}
      </span>
      {row.meta && (
        // In the field this only RESERVES the room the menu's row needs.
        <span aria-hidden={withMeta === "reserve" || undefined} className={cn("pl-2 shrink-0 text-xs font-normal text-text-muted whitespace-nowrap", withMeta === "reserve" ? "invisible" : "")}>{row.meta}</span>
      )}
    </>
  );
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
  const [open, setOpen] = React.useState(false);
  const rows: Row[] = [
    ...(allLabel ? [{ id: ALL_COURSES, color: null, code: allLabel, name: null, meta: null }] : []),
    ...courses.map(c => ({
      id: c.course_id, color: c.color, code: c.course_code || c.course_name,
      name: c.course_code ? c.course_name : null, meta: meta ? meta(c) : null,
    })),
  ];
  const chosen = rows.find(r => r.id === value) ?? rows[0];
  const pick = (id: string) => { setOpen(false); onChange(id); };

  return (
    <div className={cn("relative min-w-0 max-w-140", fullWidth ? "flex-[1_1_100%]" : "flex-[0_1_auto]")}
      onKeyDown={e => { if (e.key === "Escape" && open) { e.stopPropagation(); setOpen(false); } }}>
      <button type="button" className={`btn ${s.field}`} onClick={() => setOpen(o => !o)} aria-haspopup="listbox" aria-expanded={open}
        style={fullWidth ? { width: "100%" } : undefined}>
        <span className="grid min-w-0">
          {rows.map(row => {
            const shown = row.id === chosen?.id;
            return (
              <span key={row.id} aria-hidden={shown ? undefined : true} className={cn("[grid-area:1_/_1] flex items-center gap-2 min-w-0", shown ? "visible" : "invisible")}>
                <RowContent row={row} withMeta="reserve" />
              </span>
            );
          })}
        </span>
        <span aria-hidden="true" className={s.chevron}><Icon name="chevron-down" size={10} /></span>
      </button>
      {open && (
        <>
          <div onClick={() => setOpen(false)} className="fixed inset-0 z-30" />
          <div role="listbox" aria-label="Courses" className={s.menu}>
            {rows.map(row => {
              const on = row.id === chosen?.id;
              return (
                <button key={row.id} type="button" role="option" aria-selected={on} className={s.option} onClick={() => pick(row.id)}>
                  <RowContent row={row} withMeta="show" />
                  {/* The tick sits where the field's chevron does. */}
                  <span aria-hidden="true" className="ml-auto w-2.5 grid justify-items-center shrink-0 text-brand-forest">{on && <Icon name="check" size={12} />}</span>
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
