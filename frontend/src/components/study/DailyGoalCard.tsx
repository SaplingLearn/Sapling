"use client";

/**
 * The Study hub's Daily Goal card: today's minutes toward the goal, the last
 * seven days, and today's split across quiz / flashcards / tutor.
 *
 * The goal is edited in place: the target ("30 min") is itself the button,
 * and it turns its line into a row of presets. One tap on a preset saves it;
 * the pencil at the end is for any other number. Esc, or a press anywhere
 * else, cancels.
 * Earlier versions: a gear that opened a floating popover (it read as a
 * settings screen bolted onto the card), then a - / + stepper with Cancel and
 * Save (four controls and two clicks to do what one tap does here).
 *
 * Sizes and colours come from the app tokens (globals.css), matching the
 * side cards on the other screens (Dashboard's TodayColumn, Calendar).
 */
import React from "react";
import type { StudyDaily } from "@/lib/studyApi";
import { fmtDow } from "./studyModel";
import s from "./DailyGoalCard.module.css";

export const GOAL_MIN = 5;
export const GOAL_MAX = 600;
/** The goals most students pick, in minutes a day. Anything else is "custom". */
const PRESETS = [15, 30, 45, 60, 90];

const ACTIVITIES = [
  { key: "quiz", label: "Quiz", color: "#7A4A78" },
  { key: "flashcards", label: "Flashcards", color: "var(--brand-forest-bright)" },
  { key: "tutor", label: "Tutor", color: "#B8873F" },
] as const;

/** Figures use the display face, as the Dashboard's (`.h-serif`) do. */
const SERIF = "var(--font-display)";

function PencilIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M8.2 1.8l2 2L4 10H2v-2l6.2-6.2z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}

export function DailyGoalCard({
  daily,
  onSave,
}: {
  daily: StudyDaily | null;
  /** Persist a new goal; resolves true when it saved. */
  onSave: (minutes: number) => Promise<boolean>;
}) {
  const goal = daily?.goal_minutes ?? 30;
  const week = daily?.days || [];
  const todayRow = week[week.length - 1];
  const done = todayRow?.minutes ?? 0;
  const pct = Math.min(100, (done / goal) * 100);
  const met = done >= goal;
  const pastDays = week.slice(0, -1);
  const hit = pastDays.filter(d => d.minutes >= goal).length;
  const weekTotal = week.reduce((n, d) => n + d.minutes, 0);
  const MAX = Math.max(goal * 1.25, ...week.map(d => d.minutes), 1);

  // false = the figure; "presets" = the row of presets; "custom" = a number.
  const [editing, setEditing] = React.useState<false | "presets" | "custom">(false);
  const [draft, setDraft] = React.useState(String(goal));
  const [saving, setSaving] = React.useState(false);
  const targetRef = React.useRef<HTMLButtonElement>(null);
  const rowRef = React.useRef<HTMLDivElement | HTMLFormElement | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const returnFocus = React.useRef(false);
  const isCustom = !PRESETS.includes(goal);

  React.useEffect(() => {
    if (editing === "custom") {
      inputRef.current?.focus();
      inputRef.current?.select();
    } else if (editing === "presets") {
      const row = rowRef.current;
      (row?.querySelector<HTMLElement>('[aria-checked="true"]') ?? row?.querySelector<HTMLElement>("button"))?.focus();
    } else if (returnFocus.current) {
      returnFocus.current = false;
      targetRef.current?.focus();
    }
  }, [editing]);

  // A press anywhere outside the open editor cancels it.
  React.useEffect(() => {
    if (!editing) return;
    const onDown = (e: Event) => {
      const row = rowRef.current;
      if (row && e.target instanceof Node && row.contains(e.target)) return;
      setEditing(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [editing]);

  const open = () => { setDraft(String(goal)); setEditing("presets"); };
  const close = () => { returnFocus.current = true; setEditing(false); };
  /** Save `n` and close; on failure stay open so it can be tried again. */
  const choose = async (n: number): Promise<boolean> => {
    if (saving) return false;
    if (n === goal) { close(); return true; }
    setSaving(true);
    const ok = await onSave(n);
    setSaving(false);
    if (ok) close();
    return ok;
  };
  const submitCustom = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!(await choose(Math.round(Number(draft))))) inputRef.current?.focus();
  };
  const onEscape = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.stopPropagation(); close(); }
  };

  return (
    <div className={`card ${s.card}`} data-testid="daily-goal">
      {/* ── today ── */}
      <div className={s.head}>
        <span className="label-micro">Daily goal</span>
        {editing
          ? <span className={s.note}>minutes a day</span>
          : met
            ? <span className={s.met}>Goal met</span>
            : <span className={s.note}>{goal - done} min to go</span>}
      </div>

      {editing === "presets" ? (
        <div ref={rowRef as React.RefObject<HTMLDivElement>} className={s.editRow} role="radiogroup"
          aria-label="Daily goal, minutes a day" onKeyDown={onEscape}>
          {PRESETS.map(n => (
            <button key={n} type="button" role="radio" aria-checked={n === goal} aria-label={`${n} minutes`}
              className={s.preset} disabled={saving} onClick={() => choose(n)}>{n}</button>
          ))}
          <button type="button" className={s.preset} aria-pressed={isCustom} disabled={saving}
            aria-label={isCustom ? `Custom goal: ${goal} minutes. Change it` : "Set a custom goal"} title="Another number"
            onClick={() => setEditing("custom")}>
            {isCustom ? goal : <PencilIcon />}
          </button>
        </div>
      ) : editing === "custom" ? (
        <form ref={rowRef as React.RefObject<HTMLFormElement>} className={s.editRow} onSubmit={submitCustom} onKeyDown={onEscape}>
          <input ref={inputRef} className={s.customInput} type="number" inputMode="numeric"
            min={GOAL_MIN} max={GOAL_MAX} step={1} required
            value={draft} onChange={e => setDraft(e.target.value)} aria-label="Daily goal in minutes" />
          <span className={s.unit}>min a day</span>
          <button type="submit" className={`btn btn--primary btn--sm ${s.set}`} disabled={saving}>{saving ? "Saving" : "Set"}</button>
        </form>
      ) : (
        <div className={s.figure}>
          <span style={{ fontFamily: SERIF, fontSize: "var(--fs-2xl)", fontWeight: 600, lineHeight: 1, color: "var(--text)" }}>{done}</span>
          <span className={s.of}>of</span>
          <button ref={targetRef} type="button" className={s.target} onClick={open}
            aria-label={`Daily goal: ${goal} minutes. Change daily goal`} title="Change daily goal">
            {goal} min
            <span className={s.pencil}><PencilIcon /></span>
          </button>
        </div>
      )}

      <div className={s.progress} role="progressbar" aria-label="Today's progress toward the daily goal"
        aria-valuemin={0} aria-valuemax={goal} aria-valuenow={Math.min(done, goal)} aria-valuetext={`${done} of ${goal} minutes`}>
        <span className={s.progressFill} style={{ width: `${pct}%` }} />
      </div>

      {/* ── this week ── */}
      <div className={s.section}>
        <div className={s.subhead}>
          <span>This week</span>
          <span className={s.note}>
            {weekTotal === 0 ? "No study time yet" : `Goal met ${hit} of ${pastDays.length} days`}
          </span>
        </div>
        <div role="img" className={s.chart}
          aria-label={`Last ${week.length} days: ${week.map(d => `${fmtDow(d.date).split(",")[0]} ${d.minutes} minutes`).join(", ")}. Goal ${goal} minutes, met ${hit} of the previous ${pastDays.length} days.`}>
          <span aria-hidden="true" className={s.goalLine} style={{ bottom: `${(goal / MAX) * 100}%` }} />
          {week.map((d, i) => {
            const isToday = i === week.length - 1;
            const h = d.minutes > 0 ? Math.max(6, (Math.min(d.minutes, MAX) / MAX) * 100) : 0;
            const bg = d.minutes === 0 ? "var(--bg-soft)"
              : isToday ? "var(--brand-forest)"
              : d.minutes >= goal ? "var(--sap-300)" : "var(--ink-200)";
            return (
              <span key={d.date} className={s.col} title={`${fmtDow(d.date)}: ${d.minutes} min`}>
                <span className={s.bar} style={{ height: d.minutes > 0 ? `${h}%` : 3, background: bg }} />
              </span>
            );
          })}
        </div>
        <div className={s.days} aria-hidden="true">
          {week.map((d, i) => (
            <span key={d.date} className={i === week.length - 1 ? s.today : undefined}>
              {fmtDow(d.date).split(",")[0]}
            </span>
          ))}
        </div>
      </div>

      {/* ── today by activity ── */}
      <div className={s.section}>
        <div className={s.subhead}><span>Today by activity</span></div>
        <div className={s.rows}>
          {ACTIVITIES.map(a => {
            const min = todayRow?.[a.key] ?? 0;
            return (
              <div key={a.key} className={s.row}>
                <span className={s.rowLabel}><span className={s.dot} style={{ background: a.color }} />{a.label}</span>
                <span className={s.track}><span className={s.fill} style={{ width: `${Math.min(100, (min / goal) * 100)}%`, background: a.color }} /></span>
                <span className={s.min} style={{ color: min > 0 ? "var(--text)" : "var(--text-muted)" }}>{min} min</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
