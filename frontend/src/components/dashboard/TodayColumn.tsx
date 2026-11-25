"use client";
/**
 * The Dashboard's right column (sidebar layout): the streak, Today's plan,
 * and mastery, as three untitled cards. Their purpose reads from the content,
 * so none carries a label.
 *
 * The plan is derived ENTIRELY from data the Dashboard already loads
 * (sessions, graph nodes, upcoming assignments, and — with `learning_loop` +
 * `quiz_concept_plan` on — the shared learner-next buckets that pick the
 * quiz's concept, W8.6). There is no stored
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
import { AnimatePresence, motion } from "framer-motion";
import { Icon } from "../Icon";
import { useMotionPresets } from "@/lib/motion";
import styles from "./TodayColumn.module.css";
import { buildQuizHref } from "@/lib/quiz/source";
import { planReasonShort } from "@/lib/quiz/proposals";
import { firstNextIn } from "@/lib/learnerNext";
import type { Assignment, Session } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import type { StudyNext } from "@/lib/studyApi";

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

/**
 * The concept the plan's quiz item names, and the meta line that says why.
 * A concept worked on today holds the slot (ticked), even if that work moved
 * it out of the weak tiers or off the learner's plan — re-picking on every
 * render would swap the finished item for a fresh one and the checklist could
 * never complete. Otherwise:
 *   - learner-next on (`learnerNext` non-null): the first concept of its
 *     due → misconception → ready order that is on the scoped map, the same
 *     set Study Focus and the quiz home propose; none there = no quiz item;
 *   - off (null): the concept you're struggling with most, falling back to
 *     the shakiest one you're still learning.
 */
export function pickQuizConcept(
  concepts: GraphNode[],
  todayKey: string | null,
  learnerNext: StudyNext | null,
): { node: GraphNode; why: string } | null {
  const byScore = (a: GraphNode, b: GraphNode) => a.mastery_score - b.mastery_score;
  const doneToday = concepts
    .filter((n) => localDayKey(n.last_studied_at) === todayKey && n.mastery_tier !== "unexplored")
    .sort(byScore)[0];
  if (doneToday) return { node: doneToday, why: "reviewed today" };
  if (learnerNext) {
    const byId = new Map(concepts.map((n) => [n.id, n]));
    const next = firstNextIn(learnerNext, (id) => byId.has(id));
    const node = next ? byId.get(next.node_id) : undefined;
    return next && node ? { node, why: planReasonShort(next.reason) } : null;
  }
  const struggling = concepts.filter((n) => n.mastery_tier === "struggling").sort(byScore);
  const learning = concepts.filter((n) => n.mastery_tier === "learning").sort(byScore);
  const weak = struggling[0] ?? learning[0];
  if (!weak) return null;
  return { node: weak, why: weak.mastery_tier === "struggling" ? "you're struggling here" : "still learning" };
}

export function buildTodayPlan(input: {
  sessions: Session[];
  nodes: GraphNode[];
  /** Learner-next buckets (W8.6); null/absent = the graph-tier pick. */
  learnerNext?: StudyNext | null;
  assignments: DatedAssignment[];
  hasCourses: boolean;
  nowMs: number;
  courseLabel: (courseId: string | null | undefined) => string | null;
  relTime: (iso: string | null | undefined) => string;
}): PlanItem[] {
  const { sessions, nodes, learnerNext = null, assignments, hasCourses, nowMs, courseLabel, relTime } = input;
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

  // 2. The quiz: the learner's next concept (pickQuizConcept).
  const pick = pickQuizConcept(nodes.filter((n) => !n.is_subject_root), todayKey, learnerNext);
  if (pick) {
    const weak = pick.node;
    items.push({
      key: `quiz-${weak.id}`,
      title: `Quiz: ${weak.name}`,
      meta: join(courseLabel(weak.course_id), pick.why),
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

/** How far a plan row gives under a press. */
const PRESS_SCALE = 0.99;

function CheckBox({ done, onDark }: { done: boolean; onDark: boolean }) {
  return (
    <span aria-hidden className={styles.check} data-done={done} data-on-dark={onDark}>
      {done && <Icon name="check" size={11} />}
    </span>
  );
}

/**
 * One plan item. A ticked item rises to the top of the list (buildTodayPlan),
 * so rows glide to their new place (`layout`) instead of jumping; a row that
 * joins the list later fades up into it. The list's first paint is still.
 */
function PlanRow({ item, primary, onSelect }: { item: PlanItem; primary: boolean; onSelect: () => void }) {
  const m = useMotionPresets();
  return (
    <motion.button
      type="button"
      data-testid={item.testId}
      onClick={onSelect}
      className={styles.planRow}
      data-done={item.done}
      data-primary={primary}
      layout="position"
      {...m.fadeUp}
      transition={{ ...m.fadeUp.transition, layout: m.transition.spring.gentle }}
      whileTap={{ scale: PRESS_SCALE }}
    >
      {item.checkable ? (
        <CheckBox done={item.done} onDark={primary} />
      ) : (
        <span aria-hidden className={styles.calMark}>
          <Icon name="cal" size={14} />
        </span>
      )}
      <span className={styles.planText}>
        <span className={styles.planTitle}>{item.title}</span>
        <span className={styles.planMeta}>{item.meta}</span>
      </span>
      {item.chip && !item.done && (
        <span className={`chip ${CHIP_CLASS[item.chip.tone]} ${styles.chip}`}>{item.chip.label}</span>
      )}
      {primary && <Icon name="chev" size={12} />}
    </motion.button>
  );
}

/** The dashboard's two header actions. They sit in the greeting row, right-
 *  aligned, so the column below can start flush with the graph card. */
/** Space between dashboard panels, both across (graph ↔ column) and down
 *  the column, so the gutters read as one grid. A CSS value: the column's
 *  own gap (TodayColumn.module.css `.column`) is the same token. */
export const PANEL_GAP = "var(--sp-8)";

/** The plan reserves room for a fixed number of rows (`--plan-slots`), and a
 *  course row's track may grow to `--course-row-max`: TodayColumn.module.css. */

export function DashboardActions({ navigate }: { navigate: (href: string) => void }) {
  return (
    <div className={styles.actions}>
      <button
        type="button"
        className={`btn btn--sm ${styles.actionBtn}`}
        data-testid="dashboard-action-calendar"
        onClick={() => navigate("/calendar")}
      >
        <Icon name="cal" size={14} /> Calendar
      </button>
      <button
        type="button"
        className={`btn btn--sm btn--primary ${styles.actionBtn}`}
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
  /** Learner-next buckets for the plan's quiz item (W8.6); null = tier pick. */
  learnerNext?: StudyNext | null;
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
  const { sessions, nodes, learnerNext = null, assignments, hasCourses, stats, bestStreak, xpDays, today, weekDays, nowMs, courseLabel, relTime, navigate, openCourses, courseRows } = props;

  const plan = React.useMemo(
    () => buildTodayPlan({ sessions, nodes, learnerNext, assignments, hasCourses, nowMs, courseLabel, relTime }),
    [sessions, nodes, learnerNext, assignments, hasCourses, nowMs, courseLabel, relTime],
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
    <div data-testid="dashboard-today-column" className={styles.column}>
      {/* Streak */}
      <div className={`card ${styles.streakCard}`} data-testid="dashboard-streak">
        <div className={styles.streakTop}>
          {/* Flame + count read as one unit: a tight gap, centred on the
              number (the icon's viewBox carries its own side bearing). */}
          <div data-testid="dashboard-streak-count" className={styles.streakCount}>
            <span aria-hidden className={styles.flame} data-lit={stats.streak > 0}>
              <Icon name="fire" size={28} />
            </span>
            <div>
              <span className={`h-serif ${styles.streakNumber}`} data-lit={stats.streak > 0}>
                {stats.streak}
              </span>{" "}
              <span className={styles.streakUnit}>
                {stats.streak === 1 ? "day" : "days"}{stats.streak > 0 ? " in a row" : ""}
              </span>
            </div>
          </div>
          {/* The message rides the top row (not its own line) to keep the
              card short enough for the plan's reserved slots above it. */}
          <div className={styles.streakMessage}>
            <div className={styles.streakNote}>
              {/* Keyed on the server's streak first: activity alone (a session
                  row, a concept's last_studied_at) doesn't prove it advanced. */}
              {stats.streak > 0
                ? todayDone ? "Today counted. Nice work." : "One session today keeps it alive."
                : todayDone ? "Nice work today." : "One session today starts your streak."}
            </div>
            {!!bestStreak && bestStreak > 0 && (
              <div className={styles.muted}>best {bestStreak}</div>
            )}
          </div>
        </div>
        <div className={styles.week}>
          {weekDays.map((d) => {
            const key = localDayKey(d) as string;
            const isToday = key === todayKey;
            const done = activeDays.has(key);
            const future = d.getTime() > today.getTime();
            return (
              <div key={key} className={styles.weekCol}>
                <div className={`label-micro ${styles.weekLabel}`}>
                  {d.toLocaleDateString("en-US", { weekday: "narrow" })}
                </div>
                <div
                  aria-label={`${d.toLocaleDateString("en-US", { weekday: "long" })}${done ? ", studied" : ""}`}
                  className={styles.day}
                  data-done={done}
                  data-today={isToday}
                  data-future={future}
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
      <div className={`card ${styles.masteryCard}`} data-testid="dashboard-mastery">
        {/* The course list's own header, like "Upcoming · Calendar →": a
            label on the left so the link never sits alone on its line. */}
        <div className={styles.cardHeader}>
          <div className="label-micro">Courses</div>
          <button
            type="button"
            className={`btn btn--ghost btn--sm ${styles.linkBtn}`}
            data-testid="dashboard-courses-manage"
            onClick={openCourses}
            title="Add or remove courses, switch semester"
          >
            Manage →
          </button>
        </div>
        {!courseRows && (
          <div className={styles.emptyNote}>
            {hasCourses ? "Nothing enrolled this semester." : "No courses yet."}
          </div>
        )}
        {courseRows && (
          // grow: the rows take the card's spare height (up to
          // --course-row-max each, so a tall window doesn't strand them) and
          // space-between spreads them. minHeight 0 + overflow: a student with
          // many courses scrolls this list instead of stretching the page.
          // Basis auto, not 0: with no definite card height (mobile stacks the
          // column) a 0 basis collapsed the rows to nothing.
          <div
            data-testid="dashboard-course-rows"
            className={styles.courseRows}
            style={{ "--course-rows": React.Children.count(courseRows) } as React.CSSProperties}
          >
            {courseRows}
          </div>
        )}
        {/* Below the courses: the mastery summary across them, divided off. */}
        <div className={styles.summary}>
          {stats.total > 0 ? (
            <div className={styles.summaryFigure}>
              <span className={`h-serif ${styles.summaryNumber}`}>{stats.mastered}</span>
              <span className={styles.summaryText}>of {stats.total} concepts mastered</span>
            </div>
          ) : (
            <div className={styles.summaryEmpty}>
              No concepts yet. They appear as you study and upload course material.
            </div>
          )}
          <button
            type="button"
            className={`btn btn--ghost btn--sm ${styles.linkBtn} ${styles.treeBtn}`}
            data-testid="dashboard-mastery-tree"
            onClick={() => navigate("/tree")}
          >
            Open Tree →
          </button>
        </div>
        {stats.total > 0 && (
          <>
            <div className={styles.legendBar}>
              {legend.map(([label, n, color]) => (
                <span
                  key={label}
                  className={styles.legendSegment}
                  style={{ "--seg-flex": n, "--seg-color": color } as React.CSSProperties}
                />
              ))}
            </div>
            <div className={styles.legend}>
              {legend.map(([label, n, color]) => (
                <span key={label} className={styles.legendItem}>
                  <span className={styles.legendDot} style={{ "--seg-color": color } as React.CSSProperties} />
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
      <div className={`card ${styles.planCard}`} data-testid="dashboard-plan">
        <div className={styles.planHeader}>
          <span data-testid="dashboard-plan-progress">{doneCount} of {checkable.length} done today</span>
          <span>{today.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}</span>
        </div>
        <div
          role="progressbar"
          aria-label="Today's plan"
          aria-valuemin={0}
          aria-valuemax={checkable.length}
          aria-valuenow={doneCount}
          className={styles.progress}
        >
          <div
            className={styles.progressFill}
            style={{ "--plan-pct": `${checkable.length ? (doneCount / checkable.length) * 100 : 0}%` } as React.CSSProperties}
          />
        </div>
        {/* Room for --plan-slots items whatever today's count, so the cards
            below don't jump as the plan fills up. */}
        <div className={styles.planList}>
          <AnimatePresence initial={false}>
            {plan.map((item) => (
              <PlanRow key={item.key} item={item} primary={item.key === primaryKey} onSelect={() => select(item)} />
            ))}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
