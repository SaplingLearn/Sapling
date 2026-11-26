"use client";
/**
 * The Dashboard's right column (sidebar layout): the streak, Today's plan,
 * and mastery, as three untitled cards. Their purpose reads from the content,
 * so none carries a label.
 *
 * The plan is derived ENTIRELY from data the Dashboard already loads
 * (sessions, graph nodes, upcoming assignments). There is no stored
 * "plan" or "done" record: an item ticks itself off when the app already
 * has evidence it happened today —
 *   - the session item: a session started or ended today;
 *   - the weak-spot quiz: that concept's `last_studied_at` is today;
 *   - "Add your courses" (first-run only): the student has a course.
 * A deadline is a reminder, not a task Sapling can see you finish, so it
 * renders with a date chip instead of a checkbox and never counts toward
 * "N of M done".
 */
import React from "react";
import { Icon } from "../Icon";
import { buildQuizHref } from "@/lib/quiz/source";
import type { Assignment, Session } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import { cn } from "@/lib/cn";

type DatedAssignment = Assignment & { due_date: string };

/** Local-calendar YYYY-MM-DD. The week strip and "done today" compare in the
 *  student's own day, not UTC, or an evening session lands on tomorrow. */
export function localDayKey(d: Date | string | null | undefined): string | null {
  if (!d) return null;
  const date = typeof d === "string" ? new Date(d) : d;
  if (isNaN(date.getTime())) return null;
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${m}-${day}`;
}

export type PlanChip = { label: string; tone: "struggle" | "warn" | "err" | "info" };

export type PlanItem = {
  key: string;
  title: string;
  meta: string;
  /** Deadlines are reminders: no checkbox, excluded from the done count. */
  checkable: boolean;
  done: boolean;
  chip?: PlanChip;
  href?: string;
  action?: "openCourses";
  testId?: string;
};

/** Days the deadline is in, as the chip the old Upcoming card showed. */
/**
 * When an assignment is due, in ms. A date-only `due_date` ("2026-11-09")
 * means the END of that day in the student's own zone: `new Date()` would
 * read it as UTC midnight, so anyone west of UTC saw today's work as
 * OVERDUE from the morning on.
 */
export function dueAtMs(due: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(due);
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 23, 59, 59, 999).getTime();
  return new Date(due).getTime();
}

export function dueChip(dueIso: string, nowMs: number): PlanChip {
  const diffMs = dueAtMs(dueIso) - nowMs;
  const hours = diffMs / 3_600_000;
  const days = Math.ceil(diffMs / 86_400_000);
  if (hours <= 0) return { label: "OVERDUE", tone: "err" };
  if (hours <= 24) return { label: hours < 1 ? "NOW" : `${Math.max(1, Math.round(hours))}H`, tone: "err" };
  return { label: `${days}D`, tone: days <= 2 ? "warn" : "info" };
}

/** A deadline earns a plan slot only when it is this close. */
const DUE_SOON_DAYS = 3;

export function buildTodayPlan(input: {
  sessions: Session[];
  nodes: GraphNode[];
  assignments: DatedAssignment[];
  hasCourses: boolean;
  nowMs: number;
  courseLabel: (courseId: string | null | undefined) => string | null;
  relTime: (iso: string | null | undefined) => string;
}): PlanItem[] {
  const { sessions, nodes, assignments, hasCourses, nowMs, courseLabel, relTime } = input;
  const todayKey = localDayKey(new Date(nowMs));
  const join = (...parts: (string | null | undefined)[]) => parts.filter(Boolean).join(" · ");
  const items: PlanItem[] = [];

  // 1. The session: resume the latest, or start the first.
  if (sessions.length > 0) {
    const studiedToday = sessions.find(
      (s) => localDayKey(s.started_at) === todayKey || localDayKey(s.ended_at) === todayKey,
    );
    const s = studiedToday ?? sessions[0];
    items.push({
      key: `session-${s.id}`,
      title: studiedToday ? s.topic : `Resume ${s.topic}`,
      meta: studiedToday
        ? join(courseLabel(s.course_id), "studied today")
        : join(courseLabel(s.course_id), `left off ${relTime(s.ended_at ?? s.started_at)}`),
      checkable: true,
      done: !!studiedToday,
      href: `/learn?resume=${encodeURIComponent(s.id)}`,
      testId: `dashboard-resume-${s.id}`,
    });
  } else {
    items.push({
      key: "courses",
      title: "Add your courses",
      meta: "So your graph knows what you're studying",
      checkable: true,
      done: hasCourses,
      action: "openCourses",
    });
    items.push({
      key: "first-session",
      title: "Start your first session",
      meta: "Pick any topic to begin",
      checkable: true,
      done: false,
      href: "/learn",
      testId: "dashboard-plan-first-session",
    });
  }

  // 2. The weak spot: a quiz on the concept you're struggling with most,
  //    falling back to the shakiest one you're still learning.
  const concepts = nodes.filter((n) => !n.is_subject_root);
  const byScore = (a: GraphNode, b: GraphNode) => a.mastery_score - b.mastery_score;
  const struggling = concepts.filter((n) => n.mastery_tier === "struggling").sort(byScore);
  const learning = concepts.filter((n) => n.mastery_tier === "learning").sort(byScore);
  // A concept worked on today holds the slot (ticked), even if that work
  // moved it out of the weak tiers or another concept is now weaker —
  // re-picking the weakest on every render would swap the finished item for
  // a fresh one and the checklist could never complete.
  const doneToday = concepts
    .filter((n) => localDayKey(n.last_studied_at) === todayKey && n.mastery_tier !== "unexplored")
    .sort(byScore)[0];
  const weak = doneToday ?? struggling[0] ?? learning[0];
  if (weak) {
    items.push({
      key: `quiz-${weak.id}`,
      title: `Quiz: ${weak.name}`,
      meta: join(
        courseLabel(weak.course_id),
        doneToday ? "reviewed today"
          : weak.mastery_tier === "struggling" ? "you're struggling here" : "still learning",
      ),
      checkable: true,
      done: localDayKey(weak.last_studied_at) === todayKey,
      chip: { label: "QUIZ", tone: "struggle" },
      href: buildQuizHref({ concept: weak.id }, { kind: "dashboard", returnTo: "/dashboard" }),
      testId: "dashboard-plan-quiz",
    });
  }

  // 3. The nearest deadline, if it's close.
  const soon = [...assignments]
    .sort((a, b) => dueAtMs(a.due_date) - dueAtMs(b.due_date))
    .find((a) => dueAtMs(a.due_date) - nowMs <= DUE_SOON_DAYS * 86_400_000);
  if (soon) {
    items.push({
      key: `due-${soon.id}`,
      title: soon.title,
      meta: join(soon.course_code || soon.course_name, soon.assignment_type || "due soon"),
      checkable: false,
      done: false,
      chip: dueChip(soon.due_date, nowMs),
      href: "/calendar",
      testId: `dashboard-plan-due-${soon.id}`,
    });
  }

  // Finished items rise to the top, the way you'd tick down a list.
  return [...items.filter((i) => i.done), ...items.filter((i) => !i.done)];
}

const CHIP_CLASS: Record<PlanChip["tone"], string> = {
  struggle: "chip--err",
  warn: "chip--warn",
  err: "chip--err",
  info: "chip--info",
};

function CheckBox({ done, onDark }: { done: boolean; onDark: boolean }) {
  return (
    <span
      aria-hidden
      className={cn("w-4.5 h-4.5 rounded-sm shrink-0 grid place-items-center text-accent-fg", done ? "bg-state-mastery" : "bg-transparent")} style={{ border: `1.5px solid ${done ? "var(--state-mastery)" : onDark ? "rgba(255,255,255,0.6)" : "var(--border-strong)"}` }}
    >
      {done && <Icon name="check" size={11} />}
    </span>
  );
}

function PlanRow({ item, primary, onSelect }: { item: PlanItem; primary: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      data-testid={item.testId}
      onClick={onSelect}
      className={cn("flex items-center gap-2.5 w-full text-left rounded-md [transition:filter_var(--dur-fast)_var(--ease)]", item.done ? "py-[7px] px-1" : "p-[11px]", primary ? "text-accent-fg" : "text-text")} style={{ background: primary ? "var(--brand-forest)" : item.done ? "transparent" : "var(--bg-subtle)" }}
      onMouseEnter={(e) => { e.currentTarget.style.filter = "brightness(0.97)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.filter = ""; }}
    >
      {item.checkable ? (
        <CheckBox done={item.done} onDark={primary} />
      ) : (
        <span aria-hidden className="w-4.5 grid place-items-center shrink-0 text-warn">
          <Icon name="cal" size={14} />
        </span>
      )}
      <span className="flex-1 min-w-0">
        <span
          className={cn("block text-md font-semibold overflow-hidden text-ellipsis whitespace-nowrap", item.done ? "line-through" : "", item.done ? "text-text-muted" : "")}
        >
          {item.title}
        </span>
        <span
          className={cn("block text-xs overflow-hidden text-ellipsis whitespace-nowrap", primary ? "text-[rgba(255,255,255,0.85)]" : "text-text-muted")}
        >
          {item.meta}
        </span>
      </span>
      {item.chip && !item.done && (
        <span className={cn(`chip ${CHIP_CLASS[item.chip.tone]}`, "shrink-0")}>{item.chip.label}</span>
      )}
      {primary && <Icon name="chev" size={12} />}
    </button>
  );
}

/** The dashboard's two header actions. They sit in the greeting row, right-
 *  aligned, so the column below can start flush with the graph card. */
/** Space between dashboard panels, both across (graph ↔ column) and down
 *  the column, so the gutters read as one grid. */
export const PANEL_GAP = 16;

/** The plan reserves room for this many items, and the height of one
 *  (11px padding top and bottom around a 13px title and an 11px meta line). */
const PLAN_SLOTS = 4;
const PLAN_ROW_H = 58;

/** Tallest a course row's track may grow to fill the mastery card. */
const COURSE_ROW_MAX = 64;

export function DashboardActions({ navigate }: { navigate: (href: string) => void }) {
  return (
    <div className="flex gap-2 shrink-0 items-center">
      <button
        type="button"
        className="btn btn--sm h-10 py-0 px-4 text-md"
        data-testid="dashboard-action-calendar"
        onClick={() => navigate("/calendar")}
      >
        <Icon name="cal" size={14} /> Calendar
      </button>
      <button
        type="button"
        className="btn btn--sm btn--primary h-10 py-0 px-4 text-md"
        data-testid="dashboard-action-start"
        onClick={() => navigate("/learn")}
      >
        <Icon name="sparkle" size={14} /> Start learning
      </button>
    </div>
  );
}

export function TodayColumn(props: {
  sessions: Session[];
  nodes: GraphNode[];
  assignments: DatedAssignment[];
  hasCourses: boolean;
  stats: { streak: number; mastered: number; total: number; learning: number; struggling: number; unexplored: number };
  /** users.longest_streak, when /api/gamification/me loaded. */
  bestStreak?: number | null;
  /** YYYY-MM-DD days with XP this week (/api/gamification/activity). */
  xpDays?: Set<string>;
  today: Date;
  weekDays: Date[];
  nowMs: number;
  courseLabel: (courseId: string | null | undefined) => string | null;
  relTime: (iso: string | null | undefined) => string;
  navigate: (href: string) => void;
  openCourses: () => void;
  /** Per-course progress rows, rendered at the foot of the mastery card,
   *  under a "Courses · Manage →" header (the Courses & Semesters hub). */
  courseRows?: React.ReactNode;
}) {
  const { sessions, nodes, assignments, hasCourses, stats, bestStreak, xpDays, today, weekDays, nowMs, courseLabel, relTime, navigate, openCourses, courseRows } = props;

  const plan = React.useMemo(
    () => buildTodayPlan({ sessions, nodes, assignments, hasCourses, nowMs, courseLabel, relTime }),
    [sessions, nodes, assignments, hasCourses, nowMs, courseLabel, relTime],
  );
  const checkable = plan.filter((i) => i.checkable);
  const doneCount = checkable.filter((i) => i.done).length;
  const primaryKey = plan.find((i) => i.checkable && !i.done)?.key;

  // A day is "active" when it earned XP (the same hook advances the streak),
  // a concept was studied, or a session ran that day. XP days are UTC dates;
  // the rest are local — near midnight the two can disagree by a day.
  const activeDays = React.useMemo(() => {
    const days = new Set<string>(xpDays ?? []);
    for (const n of nodes) {
      const k = localDayKey(n.last_studied_at);
      if (k) days.add(k);
    }
    for (const s of sessions) {
      for (const iso of [s.started_at, s.ended_at]) {
        const k = localDayKey(iso);
        if (k) days.add(k);
      }
    }
    return days;
  }, [nodes, sessions, xpDays]);
  const todayKey = localDayKey(today);
  const todayDone = !!todayKey && activeDays.has(todayKey);

  const select = (item: PlanItem) => {
    if (item.action === "openCourses") openCourses();
    else if (item.href) navigate(item.href);
  };

  const legend = ([
    ["mastered", stats.mastered, "var(--state-mastery)"],
    ["learning", stats.learning, "var(--state-progress)"],
    ["struggling", stats.struggling, "var(--state-struggle)"],
    ["new", stats.unexplored, "var(--state-neutral)"],
  ] as const).filter(([, n]) => n > 0);

  return (
    <div data-testid="dashboard-today-column" className="flex flex-col gap-4 min-w-0 min-h-0">
      {/* Streak */}
      <div
        className="card py-3.5 px-4.5 [background:linear-gradient(170deg,_color-mix(in_srgb,_var(--warn-soft)_55%,_var(--bg-panel)),_var(--bg-panel)_65%)] border-[color-mix(in_srgb,_var(--warn-soft)_70%,_var(--border))]"
        data-testid="dashboard-streak"
      >
        <div className="flex items-center gap-3 mb-3">
          {/* Flame + count read as one unit: a tight gap, centred on the
              number (the icon's viewBox carries its own side bearing). */}
          <div data-testid="dashboard-streak-count" className="flex items-center gap-0.5">
            <span aria-hidden className={cn("text-alert-warn grid -ml-1", stats.streak > 0 ? "opacity-100" : "opacity-35")}>
              <Icon name="fire" size={28} />
            </span>
            <div>
              <span
                className={cn("h-serif", "text-[34px] font-semibold leading-none", stats.streak > 0 ? "text-warn" : "text-text-dim")}
              >
                {stats.streak}
              </span>{" "}
              <span className="text-md text-text-dim">
                {stats.streak === 1 ? "day" : "days"}{stats.streak > 0 ? " in a row" : ""}
              </span>
            </div>
          </div>
          {/* The message rides the top row (not its own line) to keep the
              card short enough for the plan's reserved slots above it. */}
          <div className="ml-auto self-center text-right text-[11.5px] leading-[1.35] max-w-37.5">
            <div className="text-warn">
              {/* Keyed on the server's streak first: activity alone (a session
                  row, a concept's last_studied_at) doesn't prove it advanced. */}
              {stats.streak > 0
                ? todayDone ? "Today counted. Nice work." : "One session today keeps it alive."
                : todayDone ? "Nice work today." : "One session today starts your streak."}
            </div>
            {!!bestStreak && bestStreak > 0 && (
              <div className="text-text-muted">best {bestStreak}</div>
            )}
          </div>
        </div>
        <div className="grid grid-cols-[repeat(7,_1fr)] gap-1">
          {weekDays.map((d) => {
            const key = localDayKey(d) as string;
            const isToday = key === todayKey;
            const done = activeDays.has(key);
            const future = d.getTime() > today.getTime();
            return (
              <div key={key} className="text-center">
                <div className="label-micro text-xs tracking-[0.06em]">
                  {d.toLocaleDateString("en-US", { weekday: "narrow" })}
                </div>
                <div
                  aria-label={`${d.toLocaleDateString("en-US", { weekday: "long" })}${done ? ", studied" : ""}`}
                  className={cn("mt-[3px] mx-auto mb-0 w-6 h-6 rounded-[7px] grid place-items-center text-xs font-semibold", isToday && !done ? "border-[1.5px] border-dashed border-alert-warn" : "border-0", isToday && done ? "[box-shadow:0_0_0_3px_color-mix(in_srgb,_var(--alert-warn)_30%,_transparent)]" : "", future ? "opacity-70" : "opacity-100")} style={{ background: done ? "var(--alert-warn)" : isToday ? "transparent" : "var(--bg-subtle)", color: done ? "#fff" : isToday ? "var(--warn)" : "var(--text-muted)" }}
                >
                  {d.getDate()}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Courses, then mastery */}
      {/* flex: 1 — this card takes the column's spare height, so the column
          runs the full height of the graph beside it (its course rows spread
          into it). Today's plan sits below it, at its natural height. */}
      <div
        className="card py-4 px-4.5 flex-1 flex flex-col min-h-0"
        data-testid="dashboard-mastery"
      >
        {/* The course list's own header, like "Upcoming · Calendar →": a
            label on the left so the link never sits alone on its line. */}
        <div
          className="flex items-center justify-between gap-2"
        >
          <div className="label-micro">Courses</div>
          <button
            type="button"
            className="btn btn--ghost btn--sm -mr-2 text-sm h-6 py-0 px-2"
            data-testid="dashboard-courses-manage"
            onClick={openCourses}
            title="Add or remove courses, switch semester"
          >
            Manage →
          </button>
        </div>
        {!courseRows && (
          <div className="text-sm text-text-muted mt-1">
            {hasCourses ? "Nothing enrolled this semester." : "No courses yet."}
          </div>
        )}
        {courseRows && (
          // basis 0 + grow: the rows take the card's spare height (up to
          // COURSE_ROW_MAX each, so a tall window doesn't strand them) and
          // space-between spreads them. minHeight 0 + overflow: a student with
          // many courses scrolls this list instead of stretching the page.
          <div
            data-testid="dashboard-course-rows"
            className="mt-1 flex-[1_1_auto] min-h-0 overflow-y-auto flex flex-col justify-between gap-1" style={{ maxHeight: React.Children.count(courseRows) * COURSE_ROW_MAX }}
          >
            {courseRows}
          </div>
        )}
        {/* Below the courses: the mastery summary across them, divided off. */}
        <div
          className="flex items-start justify-between gap-2 mt-4.5 pt-3 border-t border-t-border"
        >
          {stats.total > 0 ? (
            <div className="flex items-baseline gap-1.5">
              <span className="h-serif text-3xl font-semibold leading-none">{stats.mastered}</span>
              <span className="text-md text-text-muted">of {stats.total} concepts mastered</span>
            </div>
          ) : (
            <div className="text-sm text-text-muted pt-[3px]">
              No concepts yet. They appear as you study and upload course material.
            </div>
          )}
          <button
            type="button"
            className="btn btn--ghost btn--sm shrink-0 -mr-2 -mt-0.5 text-sm h-6 py-0 px-2"
            data-testid="dashboard-mastery-tree"
            onClick={() => navigate("/tree")}
          >
            Open Tree →
          </button>
        </div>
        {stats.total > 0 && (
          <>
            <div className="flex h-2 rounded-[99px] overflow-hidden gap-0.5 mt-2">
              {legend.map(([label, n, color]) => (
                <span key={label} style={{ flex: n, background: color }} />
              ))}
            </div>
            <div className="flex flex-wrap gap-y-1 gap-x-3 mt-1.5 text-xs text-text-muted">
              {legend.map(([label, n, color]) => (
                <span key={label} className="inline-flex items-center gap-[5px]">
                  <span className="w-[7px] h-[7px] rounded-[50%]" style={{ background: color }} />
                  {n} {label}
                </span>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Today's plan */}
      {/* Last card: 28px at the bottom keeps its last item above the floating
          report button, which is pinned over the column's bottom-right corner. */}
      <div className="card pt-4 px-4.5 pb-7" data-testid="dashboard-plan">
        <div className="flex justify-between text-sm text-text-muted">
          <span data-testid="dashboard-plan-progress">{doneCount} of {checkable.length} done today</span>
          <span>{today.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}</span>
        </div>
        <div
          role="progressbar"
          aria-label="Today's plan"
          aria-valuemin={0}
          aria-valuemax={checkable.length}
          aria-valuenow={doneCount}
          className="h-1 rounded-[99px] bg-bg-soft overflow-hidden mt-2 mx-0 mb-2.5"
        >
          <div
            className="h-full rounded-[99px] bg-state-mastery [transition:width_var(--dur)_var(--ease)]" style={{ width: `${checkable.length ? (doneCount / checkable.length) * 100 : 0}%` }}
          />
        </div>
        {/* Room for PLAN_SLOTS items whatever today's count, so the cards
            below don't jump as the plan fills up. */}
        <div className="flex flex-col gap-1.5" style={{ minHeight: PLAN_SLOTS * PLAN_ROW_H + (PLAN_SLOTS - 1) * 6 }}>
          {plan.map((item) => (
            <PlanRow key={item.key} item={item} primary={item.key === primaryKey} onSelect={() => select(item)} />
          ))}
        </div>
      </div>
    </div>
  );
}
