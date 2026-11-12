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
import type { StudyDaily, StudyDay } from "@/lib/studyApi";
import s from "./DailyGoalCard.module.css";
import { GOAL_MAX, GOAL_MIN, PRESETS, dayBar, goalStats, type GoalStats } from "./dailyGoalModel";
import { fmtDow } from "./studyModel";

const ACTIVITIES = [
  { key: "quiz", label: "Quiz", color: "#7A4A78" },
  { key: "flashcards", label: "Flashcards", color: "var(--brand-forest-bright)" },
  { key: "tutor", label: "Tutor", color: "#B8873F" },
] as const;

/** Figures use the display face, as the Dashboard's (`.h-serif`) do. */
const SERIF = "var(--font-display)";

/** "Fri" from a YYYY-MM-DD day. */
const dow = (date: string) => fmtDow(date).split(",")[0];

function PencilIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M8.2 1.8l2 2L4 10H2v-2l6.2-6.2z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}

/** false = the figure; "presets" = the row of presets; "custom" = a number. */
type Editing = false | "presets" | "custom";

/**
 * The in-place goal editor's state: which form the goal line is in, the custom
 * draft, and where focus goes as it opens and closes.
 */
function useGoalEdit(goal: number, onSave: (minutes: number) => Promise<boolean>) {
  const [editing, setEditing] = React.useState<Editing>(false);
  const [draft, setDraft] = React.useState(String(goal));
  const [saving, setSaving] = React.useState(false);
  const targetRef = React.useRef<HTMLButtonElement>(null);
  const rowRef = React.useRef<HTMLDivElement | HTMLFormElement | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const returnFocus = React.useRef(false);

  React.useEffect(() => {
    if (editing === "custom") {
      inputRef.current?.focus();
      inputRef.current?.select();
      return;
    }
    if (editing === "presets") {
      // The current goal's preset, else the first one.
      const row = rowRef.current;
      (row?.querySelector<HTMLElement>('[aria-checked="true"]') ?? row?.querySelector<HTMLElement>("button"))?.focus();
      return;
    }
    if (!returnFocus.current) return;
    returnFocus.current = false;
    targetRef.current?.focus();
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
  const edit = { editing, draft, saving, setDraft, open, choose, submitCustom, onEscape, custom: () => setEditing("custom") };
  // The refs travel apart from the state: each goes straight to the element it names.
  return { edit, targetRef, rowRef, inputRef };
}

type GoalEdit = ReturnType<typeof useGoalEdit>["edit"];
type RowRef = React.RefObject<HTMLDivElement | HTMLFormElement | null>;

/** The note beside "Daily goal": what the editor's numbers mean, or how today stands. */
function HeadNote({ editing, stats }: { editing: boolean; stats: GoalStats }) {
  if (editing) return <span className={s.note}>minutes a day</span>;
  if (stats.met) return <span className={s.met}>Goal met</span>;
  return <span className={s.note}>{stats.goal - stats.done} min to go</span>;
}

/** The goal line as a row of presets: one tap saves; the last slot is "another number". */
function PresetRow({ goal, edit, rowRef }: { goal: number; edit: GoalEdit; rowRef: RowRef }) {
  const isCustom = !PRESETS.includes(goal);
  return (
    <div ref={rowRef as React.RefObject<HTMLDivElement>} className={s.editRow} role="radiogroup"
      aria-label="Daily goal, minutes a day" onKeyDown={edit.onEscape}>
      {PRESETS.map(n => (
        <button key={n} type="button" role="radio" aria-checked={n === goal} aria-label={`${n} minutes`}
          className={s.preset} disabled={edit.saving} onClick={() => edit.choose(n)}>{n}</button>
      ))}
      <button type="button" className={s.preset} aria-pressed={isCustom} disabled={edit.saving}
        aria-label={isCustom ? `Custom goal: ${goal} minutes. Change it` : "Set a custom goal"} title="Another number"
        onClick={edit.custom}>
        {isCustom ? goal : <PencilIcon />}
      </button>
    </div>
  );
}

/** The goal line as a number field, for a goal that is not a preset. */
function CustomRow({ edit, rowRef, inputRef }: { edit: GoalEdit; rowRef: RowRef; inputRef: React.RefObject<HTMLInputElement | null> }) {
  return (
    <form ref={rowRef as React.RefObject<HTMLFormElement>} className={s.editRow} onSubmit={edit.submitCustom} onKeyDown={edit.onEscape}>
      <input ref={inputRef} className={s.customInput} type="number" inputMode="numeric"
        min={GOAL_MIN} max={GOAL_MAX} step={1} required
        value={edit.draft} onChange={e => edit.setDraft(e.target.value)} aria-label="Daily goal in minutes" />
      <span className={s.unit}>min a day</span>
      <button type="submit" className={`btn btn--primary btn--sm ${s.set}`} disabled={edit.saving}>{edit.saving ? "Saving" : "Set"}</button>
    </form>
  );
}

/** The goal line at rest: today's minutes "of" the target, which is the edit button. */
function Figure({ stats, onEdit, targetRef }: { stats: GoalStats; onEdit: () => void; targetRef: React.RefObject<HTMLButtonElement | null> }) {
  return (
    <div className={s.figure}>
      <span style={{ fontFamily: SERIF, fontSize: "var(--fs-2xl)", fontWeight: 600, lineHeight: 1, color: "var(--text)" }}>{stats.done}</span>
      <span className={s.of}>of</span>
      <button ref={targetRef} type="button" className={s.target} onClick={onEdit}
        aria-label={`Daily goal: ${stats.goal} minutes. Change daily goal`} title="Change daily goal">
        {stats.goal} min
        <span className={s.pencil}><PencilIcon /></span>
      </button>
    </div>
  );
}

/** The last seven days as bars against the goal line. */
function WeekChart({ stats }: { stats: GoalStats }) {
  const { week, goal, hit, pastDays, max } = stats;
  const last = week.length - 1;
  const spoken = week.map(d => `${dow(d.date)} ${d.minutes} minutes`).join(", ");
  return (
    <div className={s.section}>
      <div className={s.subhead}>
        <span>This week</span>
        <span className={s.note}>
          {stats.weekTotal === 0 ? "No study time yet" : `Goal met ${hit} of ${pastDays} days`}
        </span>
      </div>
      <div role="img" className={s.chart}
        aria-label={`Last ${week.length} days: ${spoken}. Goal ${goal} minutes, met ${hit} of the previous ${pastDays} days.`}>
        <span aria-hidden="true" className={s.goalLine} style={{ bottom: `${(goal / max) * 100}%` }} />
        {week.map((d, i) => (
          <span key={d.date} className={s.col} title={`${fmtDow(d.date)}: ${d.minutes} min`}>
            <span className={s.bar} style={dayBar(d.minutes, i === last, goal, max)} />
          </span>
        ))}
      </div>
      <div className={s.days} aria-hidden="true">
        {week.map((d, i) => <span key={d.date} className={i === last ? s.today : undefined}>{dow(d.date)}</span>)}
      </div>
    </div>
  );
}

/** Today's minutes split across quiz, flashcards and the tutor. */
function ActivityRows({ today, goal }: { today: StudyDay | undefined; goal: number }) {
  return (
    <div className={s.section}>
      <div className={s.subhead}><span>Today by activity</span></div>
      <div className={s.rows}>
        {ACTIVITIES.map(a => {
          const min = today?.[a.key] ?? 0;
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
  const stats = goalStats(daily);
  const { goal, done } = stats;
  const { edit, targetRef, rowRef, inputRef } = useGoalEdit(goal, onSave);

  return (
    <div className={`card ${s.card}`} data-testid="daily-goal">
      {/* ── today ── */}
      <div className={s.head}>
        <span className="label-micro">Daily goal</span>
        <HeadNote editing={!!edit.editing} stats={stats} />
      </div>
      {/* The goal line: the figure, or one of the editor's two forms in its place. */}
      {!edit.editing && <Figure stats={stats} onEdit={edit.open} targetRef={targetRef} />}
      {edit.editing === "presets" && <PresetRow goal={goal} edit={edit} rowRef={rowRef} />}
      {edit.editing === "custom" && <CustomRow edit={edit} rowRef={rowRef} inputRef={inputRef} />}
      <div className={s.progress} role="progressbar" aria-label="Today's progress toward the daily goal"
        aria-valuemin={0} aria-valuemax={goal} aria-valuenow={Math.min(done, goal)} aria-valuetext={`${done} of ${goal} minutes`}>
        <span className={s.progressFill} style={{ width: `${stats.pct}%` }} />
      </div>
      <WeekChart stats={stats} />
      <ActivityRows today={stats.today} goal={goal} />
    </div>
  );
}
