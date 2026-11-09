"use client";

/**
 * The Study hub's Daily Goal card: today's minutes toward the goal, the last
 * seven days, and today's split across quiz / flashcards / tutor.
 *
 * The goal is edited in place: the target ("30 min") is itself the button,
 * and it opens a small stepper on the same line (Enter saves, Esc cancels).
 * There used to be a gear beside the label that opened a floating popover,
 * which read as a settings screen bolted onto the card.
 *
 * Sizes and colours come from the app tokens (globals.css), matching the
 * side cards on the other screens (Dashboard's TodayColumn, Calendar).
 */
import React from "react";
import type { StudyDaily } from "@/lib/studyApi";
import { INHERIT_FONT } from "@/lib/inheritFont";
import { fmtDow } from "./studyModel";
import s from "./DailyGoalCard.module.css";

export const GOAL_MIN = 5;
export const GOAL_MAX = 600;
const STEP = 5;

const ACTIVITIES = [
  { key: "quiz", label: "Quiz", color: "#7A4A78" },
  { key: "flashcards", label: "Flashcards", color: "var(--brand-forest-bright)" },
  { key: "tutor", label: "Tutor", color: "#B8873F" },
] as const;

const SERIF = "var(--font-serif), 'Aleo', georgia, serif";

const clampGoal = (n: number) => Math.min(GOAL_MAX, Math.max(GOAL_MIN, n));

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

  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(String(goal));
  const [saving, setSaving] = React.useState(false);
  const targetRef = React.useRef<HTMLButtonElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const returnFocus = React.useRef(false);

  React.useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    } else if (returnFocus.current) {
      returnFocus.current = false;
      targetRef.current?.focus();
    }
  }, [editing]);

  const open = () => { setDraft(String(goal)); setEditing(true); };
  const close = () => { returnFocus.current = true; setEditing(false); };
  const step = (dir: 1 | -1) => {
    const n = Math.round(Number(draft));
    const base = Number.isFinite(n) ? n : goal;
    // Snap to the step grid first, so 33 goes to 35 / 30 rather than 38 / 28.
    const next = dir > 0 ? Math.floor(base / STEP) * STEP + STEP : Math.ceil(base / STEP) * STEP - STEP;
    setDraft(String(clampGoal(next)));
  };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (saving) return;
    const n = Math.round(Number(draft));
    if (n === goal) { close(); return; }
    setSaving(true);
    const ok = await onSave(n);
    setSaving(false);
    if (ok) close();
    else inputRef.current?.focus();
  };

  const smallBtn: React.CSSProperties = {
    height: 28, padding: "0 10px", borderRadius: "var(--r-sm)", ...INHERIT_FONT,
    fontSize: "var(--fs-sm)", fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap",
  };

  return (
    <div className={`card ${s.card}`} data-testid="daily-goal">
      {/* ── today ── */}
      <div className={s.head}>
        <span className="label-micro">Daily goal</span>
        {!editing && (
          met
            ? <span className={s.met}>Goal met</span>
            : <span className={s.note}>{goal - done} min to go</span>
        )}
      </div>

      {editing ? (
        <form className={s.editRow} onSubmit={submit}
          onKeyDown={e => { if (e.key === "Escape") { e.stopPropagation(); close(); } }}>
          <span className={s.stepper}>
            <button type="button" className={s.stepBtn} aria-label="Decrease goal" onClick={() => step(-1)}
              disabled={Number(draft) <= GOAL_MIN}>−</button>
            <input ref={inputRef} className={s.stepInput} type="number" inputMode="numeric"
              min={GOAL_MIN} max={GOAL_MAX} step={STEP} required
              value={draft} onChange={e => setDraft(e.target.value)} aria-label="Daily goal in minutes" />
            <button type="button" className={s.stepBtn} aria-label="Increase goal" onClick={() => step(1)}
              disabled={Number(draft) >= GOAL_MAX}>+</button>
          </span>
          <span className={s.unit}>min a day</span>
          <span className={s.editActions}>
            <button type="button" className={s.cancel} onClick={close} style={smallBtn}>Cancel</button>
            <button type="submit" className={s.save} disabled={saving} style={smallBtn}>{saving ? "Saving" : "Save"}</button>
          </span>
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
