"use client";
/**
 * The Dashboard's right column (sidebar layout): Today's plan, the streak,
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
export function dueChip(dueIso: string, nowMs: number): PlanChip {
  const diffMs = new Date(dueIso).getTime() - nowMs;
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
  const weak = struggling[0] ?? learning[0];
  if (weak) {
    items.push({
      key: `quiz-${weak.id}`,
      title: `Quiz: ${weak.name}`,
      meta: join(
        courseLabel(weak.course_id),
        weak.mastery_tier === "struggling" ? "you're struggling here" : "still learning",
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
    .sort((a, b) => new Date(a.due_date).getTime() - new Date(b.due_date).getTime())
    .find((a) => new Date(a.due_date).getTime() - nowMs <= DUE_SOON_DAYS * 86_400_000);
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
      style={{
        width: 18, height: 18, borderRadius: 6, flexShrink: 0,
        display: "grid", placeItems: "center",
        background: done ? "var(--state-mastery)" : "transparent",
        border: `1.5px solid ${done ? "var(--state-mastery)" : onDark ? "rgba(255,255,255,0.6)" : "var(--border-strong)"}`,
        color: "#fff",
      }}
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
      style={{
        display: "flex", alignItems: "center", gap: 10, width: "100%", textAlign: "left",
        padding: item.done ? "7px 4px" : "11px 11px",
        borderRadius: "var(--r-md)",
        background: primary ? "var(--brand-forest)" : item.done ? "transparent" : "var(--bg-subtle)",
        color: primary ? "#fff" : "var(--text)",
        transition: "filter var(--dur-fast) var(--ease)",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.filter = "brightness(0.97)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.filter = ""; }}
    >
      {item.checkable ? (
        <CheckBox done={item.done} onDark={primary} />
      ) : (
        <span aria-hidden style={{ width: 18, display: "grid", placeItems: "center", flexShrink: 0, color: "var(--warn)" }}>
          <Icon name="cal" size={14} />
        </span>
      )}
      <span style={{ flex: 1, minWidth: 0 }}>
        <span
          style={{
            display: "block", fontSize: 13, fontWeight: 600,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            textDecoration: item.done ? "line-through" : undefined,
            color: item.done ? "var(--text-muted)" : undefined,
          }}
        >
          {item.title}
        </span>
        <span
          style={{
            display: "block", fontSize: 11,
            color: primary ? "rgba(255,255,255,0.85)" : "var(--text-muted)",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}
        >
          {item.meta}
        </span>
      </span>
      {item.chip && !item.done && (
        <span className={`chip ${CHIP_CLASS[item.chip.tone]}`} style={{ flexShrink: 0 }}>{item.chip.label}</span>
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
const COURSE_ROW_MAX = 56;

export function DashboardActions({ navigate }: { navigate: (href: string) => void }) {
  return (
    <div style={{ display: "flex", gap: 8, flexShrink: 0, alignItems: "center" }}>
      <button
        type="button"
        className="btn btn--sm"
        data-testid="dashboard-action-calendar"
        onClick={() => navigate("/calendar")}
        style={{ height: 40, padding: "0 16px", fontSize: 13 }}
      >
        <Icon name="cal" size={14} /> Calendar
      </button>
      <button
        type="button"
        className="btn btn--sm btn--primary"
        data-testid="dashboard-action-start"
        onClick={() => navigate("/learn")}
        style={{ height: 40, padding: "0 16px", fontSize: 13 }}
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
  /** Per-course progress rows, rendered at the foot of the mastery card. */
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
    <div data-testid="dashboard-today-column" style={{ display: "flex", flexDirection: "column", gap: PANEL_GAP, minWidth: 0, minHeight: 0 }}>
      {/* Today's plan */}
      <div className="card" data-testid="dashboard-plan" style={{ padding: "16px 18px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--text-muted)" }}>
          <span data-testid="dashboard-plan-progress">{doneCount} of {checkable.length} done today</span>
          <span>{today.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}</span>
        </div>
        <div
          role="progressbar"
          aria-label="Today's plan"
          aria-valuemin={0}
          aria-valuemax={checkable.length}
          aria-valuenow={doneCount}
          style={{ height: 4, borderRadius: 99, background: "var(--bg-soft)", overflow: "hidden", margin: "8px 0 10px" }}
        >
          <div
            style={{
              height: "100%", borderRadius: 99, background: "var(--state-mastery)",
              width: `${checkable.length ? (doneCount / checkable.length) * 100 : 0}%`,
              transition: "width var(--dur) var(--ease)",
            }}
          />
        </div>
        {/* Room for PLAN_SLOTS items whatever today's count, so the cards
            below don't jump as the plan fills up. */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6, minHeight: PLAN_SLOTS * PLAN_ROW_H + (PLAN_SLOTS - 1) * 6 }}>
          {plan.map((item) => (
            <PlanRow key={item.key} item={item} primary={item.key === primaryKey} onSelect={() => select(item)} />
          ))}
        </div>
      </div>

      {/* Streak */}
      <div
        className="card"
        data-testid="dashboard-streak"
        style={{
          padding: "14px 18px",
          background: "linear-gradient(170deg, color-mix(in srgb, var(--warn-soft) 55%, var(--bg-panel)), var(--bg-panel) 65%)",
          borderColor: "color-mix(in srgb, var(--warn-soft) 70%, var(--border))",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-end", gap: 12, marginBottom: 12 }}>
          <span aria-hidden style={{ color: "var(--alert-warn)", opacity: stats.streak > 0 ? 1 : 0.35, display: "grid" }}>
            <Icon name="fire" size={28} />
          </span>
          <div>
            <span
              className="h-serif"
              style={{ fontSize: 34, fontWeight: 600, lineHeight: 1, color: stats.streak > 0 ? "var(--warn)" : "var(--text-dim)" }}
            >
              {stats.streak}
            </span>{" "}
            <span style={{ fontSize: 13, color: "var(--text-dim)" }}>
              {stats.streak === 1 ? "day" : "days"}{stats.streak > 0 ? " in a row" : ""}
            </span>
          </div>
          {/* The message rides the top row (not its own line) to keep the
              card short enough for the plan's reserved slots above it. */}
          <div style={{ marginLeft: "auto", alignSelf: "center", textAlign: "right", fontSize: 11.5, lineHeight: 1.35, maxWidth: 150 }}>
            <div style={{ color: "var(--warn)" }}>
              {/* Keyed on the server's streak first: activity alone (a session
                  row, a concept's last_studied_at) doesn't prove it advanced. */}
              {stats.streak > 0
                ? todayDone ? "Today counted. Nice work." : "One session today keeps it alive."
                : todayDone ? "Nice work today." : "One session today starts your streak."}
            </div>
            {!!bestStreak && bestStreak > 0 && (
              <div style={{ color: "var(--text-muted)" }}>best {bestStreak}</div>
            )}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 4 }}>
          {weekDays.map((d) => {
            const key = localDayKey(d) as string;
            const isToday = key === todayKey;
            const done = activeDays.has(key);
            const future = d.getTime() > today.getTime();
            return (
              <div key={key} style={{ textAlign: "center" }}>
                <div className="label-micro" style={{ fontSize: 9.5, letterSpacing: "0.06em" }}>
                  {d.toLocaleDateString("en-US", { weekday: "narrow" })}
                </div>
                <div
                  aria-label={`${d.toLocaleDateString("en-US", { weekday: "long" })}${done ? ", studied" : ""}`}
                  style={{
                    margin: "3px auto 0", width: 24, height: 24, borderRadius: 7,
                    display: "grid", placeItems: "center", fontSize: 11, fontWeight: 600,
                    background: done ? "var(--alert-warn)" : isToday ? "transparent" : "var(--bg-subtle)",
                    color: done ? "#fff" : isToday ? "var(--warn)" : "var(--text-muted)",
                    border: isToday && !done ? "1.5px dashed var(--alert-warn)" : "none",
                    boxShadow: isToday && done ? "0 0 0 3px color-mix(in srgb, var(--alert-warn) 30%, transparent)" : undefined,
                    opacity: future ? 0.7 : 1,
                  }}
                >
                  {d.getDate()}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Mastery */}
      {/* flex: 1 — the last card takes the rest of the column, so the column
          runs the full height of the graph beside it. */}
      <div
        className="card"
        data-testid="dashboard-mastery"
        // Bottom padding 10 + the 24px link: the link's centre sits 22px off
        // the card's bottom edge — the same line as the graph's legend
        // (bottom: 14, 16px tall) in the card beside it.
        style={{ padding: "16px 18px 10px", flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}
      >
        {stats.total > 0 ? (
          <>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 8 }}>
              <span className="h-serif" style={{ fontSize: 26, fontWeight: 600, lineHeight: 1 }}>{stats.mastered}</span>
              <span style={{ fontSize: 13, color: "var(--text-muted)" }}>of {stats.total} concepts mastered</span>
            </div>
            <div style={{ display: "flex", height: 8, borderRadius: 99, overflow: "hidden", gap: 2 }}>
              {legend.map(([label, n, color]) => (
                <span key={label} style={{ flex: n, background: color }} />
              ))}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", marginTop: 6, fontSize: 11, color: "var(--text-muted)" }}>
              {legend.map(([label, n, color]) => (
                <span key={label} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: color }} />
                  {n} {label}
                </span>
              ))}
            </div>
          </>
        ) : (
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            No concepts yet. They appear as you study and upload course material.
          </div>
        )}
        {courseRows && (
          // The rows share the card's spare height up to COURSE_ROW_MAX each,
          // so a tall window doesn't strand them far apart; anything beyond
          // that falls above the footer link (marginTop: auto).
          <div
            data-testid="dashboard-course-rows"
            style={{
              marginTop: 10, paddingTop: 8, borderTop: "1px solid var(--border)",
              // basis 0 + grow: take the spare height, but never more than
              // COURSE_ROW_MAX per row; space-between spreads them within it.
              flex: "1 1 0", minHeight: "min-content",
              maxHeight: React.Children.count(courseRows) * COURSE_ROW_MAX,
              display: "flex", flexDirection: "column", justifyContent: "space-between", gap: 4,
            }}
          >
            {courseRows}
          </div>
        )}
        {/* Bottom-left, so it lines up with the graph's legend row and stays
            clear of the floating report button in the bottom-right corner. */}
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          data-testid="dashboard-mastery-tree"
          onClick={() => navigate("/tree")}
          style={{ alignSelf: "flex-start", marginTop: "auto", marginLeft: -8, fontSize: 12, height: 24, padding: "0 8px" }}
        >
          Open Tree →
        </button>
      </div>
    </div>
  );
}
