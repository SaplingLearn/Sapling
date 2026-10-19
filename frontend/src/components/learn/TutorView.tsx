"use client";
// The Clov tutor view of /learn (redesign prompt 04): the conversation-first
// presentation of the SAME learning loop LoopLearn runs. Everything here is a
// view — welcome, top bar, context chips, history, goal/plan, materials and
// map panels. Session, goal, diagnosis, plan, phase and every request stay in
// LoopLearn's one controller; these pieces receive its state and call its
// handlers. Pen frames s3Kxuz/wRolX (welcome), ULhG3/rIzSa (active), HHU6e
// (desktop context), WCplx (phone Map), cSgSE (phone goal & plan) and hgkZT
// (history, materials, interruption, session actions):
// https://app.pen.dev/s/sxEA2n5Ikk7KWUOanWPghMWYFFS0SbPgbkwkIm9dLYA
import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import Link from "next/link";

import { getDocuments, getSessions, type LoopOpenSession, type Session } from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";
import { BotanicalIcon, SaplingAction, SaplingComposer, StatusMessage } from "@/components/sapling";
import styles from "./TutorView.module.css";

export type TutorContextTab = "goal" | "materials" | "map";

export const CONTEXT_TITLES: Record<TutorContextTab, string> = {
  goal: "Your goal & plan",
  materials: "Course materials",
  map: "Knowledge map",
};
const CONTEXT_CHIPS: { id: TutorContextTab; label: string }[] = [
  { id: "goal", label: "Goal & plan" },
  { id: "materials", label: "Materials" },
  { id: "map", label: "Map" },
];

/** Starter prompts SEED the composer; the student finishes and sends them.
 *  Nothing is sent, started or graded by picking one. */
export const STARTER_PROMPTS: { label: string; seed: string }[] = [
  { label: "Explain a concept", seed: "Explain " },
  { label: "Connect the ideas", seed: "Help me connect " },
  { label: "Work through an example", seed: "Walk me through an example of " },
];

/** Conversation seeds while teaching: sent as ordinary chat turns through the
 *  loop's chat stream. They ask for teaching, never for a grade. */
export const CONVERSATION_SEEDS = {
  confused: "I'm confused. Can you explain that another way?",
  example: "Can you show me another example?",
} as const;

// ── Top bar ────────────────────────────────────────────────────────────────

export function TutorBar({
  course,
  historyOpen,
  onHistory,
  newSession,
  menu,
}: {
  /** The course control (a select with several courses, else the course code). */
  course: React.ReactNode;
  historyOpen: boolean;
  onHistory: () => void;
  /** The shared "+ New session" control (its confirmation is the controller's). */
  newSession: React.ReactNode;
  menu: React.ReactNode;
}) {
  return (
    <header className={styles.bar} data-testid="tutor-bar">
      <div className={styles.crumbs}>
        {course}
        <span aria-hidden="true" className={styles.crumbSep}>/</span>
        <span className={styles.crumbTitle}>Clov tutor</span>
      </div>
      <div className={styles.barActions}>
        <button
          type="button"
          className={styles.barButton}
          data-testid="tutor-history-open"
          aria-haspopup="dialog"
          aria-expanded={historyOpen}
          onClick={onHistory}
        >
          <HistoryGlyph />
          <span className={styles.barLabel}>History</span>
        </button>
        {newSession}
        {menu}
      </div>
    </header>
  );
}

function HistoryGlyph() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d="M3 12a9 9 0 1 0 3-6.7M3 4v4h4M12 7v5l3 2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export interface TutorMenuItem {
  id: string;
  label: string;
  onSelect?: () => void;
  href?: string;
  disabled?: boolean;
}

/** Session actions: a disclosure (button + list of real controls). Escape and
 *  an outside click close it and return focus to the button. */
export function TutorMenu({ items }: { items: TutorMenuItem[] }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!panelRef.current?.contains(target) && !buttonRef.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  const close = () => {
    setOpen(false);
    buttonRef.current?.focus();
  };
  return (
    <div className={styles.menu}>
      <button
        ref={buttonRef}
        type="button"
        className={styles.barButton}
        data-testid="tutor-menu"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label="Session actions"
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden="true" className={styles.dots}>•••</span>
      </button>
      {open && (
        <div
          ref={panelRef}
          id={panelId}
          className={styles.menuPanel}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.stopPropagation();
              close();
            }
          }}
        >
          <ul className={styles.menuList}>
            {items.map((item) => (
              <li key={item.id}>
                {item.href ? (
                  <Link href={item.href} className={styles.menuItem} data-testid={`tutor-menu-${item.id}`} onClick={() => setOpen(false)}>
                    {item.label}
                  </Link>
                ) : (
                  <button
                    type="button"
                    className={styles.menuItem}
                    data-testid={`tutor-menu-${item.id}`}
                    disabled={item.disabled}
                    onClick={() => {
                      setOpen(false);
                      item.onSelect?.();
                    }}
                  >
                    {item.label}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Context chips + panels ───────────────────────────────────────────────

export function ContextChips({
  active,
  onSelect,
  panelId,
}: {
  active: TutorContextTab | null;
  onSelect: (tab: TutorContextTab) => void;
  /** The desktop panel the chips control (absent on a phone: the chip opens a dialog). */
  panelId?: string;
}) {
  return (
    <div className={styles.chips} role="group" aria-label="Session context">
      {CONTEXT_CHIPS.map((chip) => (
        <button
          key={chip.id}
          type="button"
          className={styles.chip}
          data-testid={`tutor-context-${chip.id}`}
          data-active={active === chip.id || undefined}
          aria-expanded={active === chip.id}
          aria-controls={panelId}
          aria-haspopup={panelId ? undefined : "dialog"}
          onClick={() => onSelect(chip.id)}
        >
          {chip.label}
        </button>
      ))}
    </div>
  );
}

export interface RouteEntry {
  id: string;
  name: string;
  why?: string;
  current: boolean;
  evidence: string | null;
}

/** Goal & plan context: the goal read-only while teaching (a new goal is a new
 *  session), the plan in server order with why each concept is there. */
export function GoalPlanContext({
  goalText,
  scope,
  route,
  teaching,
  diagnosis,
  onEditGoal,
  onNewSession,
  emptyCopy,
}: {
  goalText: string;
  scope: string | null;
  route: RouteEntry[];
  teaching: boolean;
  diagnosis: React.ReactNode;
  onEditGoal?: () => void;
  onNewSession?: () => void;
  emptyCopy: string;
}) {
  return (
    <div className={styles.context} data-testid="tutor-goal-plan">
      <section className={styles.contextSection}>
        <p className="sapling-eyebrow">Session goal</p>
        <p className={styles.goalText}>{goalText}</p>
        {scope && <p className={styles.muted}>{scope}</p>}
      </section>
      <section className={styles.contextSection} aria-label="Plan">
        {route.length > 0 ? (
          <ol className={styles.route}>
            {route.map((entry) => (
              <li key={entry.id} data-testid={`tutor-route-${entry.id}`} data-current={entry.current || undefined}>
                <span className={styles.routeMark} aria-hidden="true" />
                <div>
                  <p className={styles.routeName}>{entry.name}</p>
                  <p className={styles.routeDetail}>
                    {[entry.current ? "Working on this now" : null, entry.why, entry.evidence].filter(Boolean).join(" · ")}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className={styles.muted}>{emptyCopy}</p>
        )}
      </section>
      {diagnosis}
      {teaching ? (
        <section className={styles.contextSection}>
          <p className={styles.muted}>To change the goal, start a new session.</p>
          {onNewSession && (
            <SaplingAction tone="secondary" data-testid="tutor-goal-new-session" onClick={onNewSession}>
              Start a new session
            </SaplingAction>
          )}
        </section>
      ) : onEditGoal ? (
        <SaplingAction tone="secondary" data-testid="tutor-goal-edit" onClick={onEditGoal}>
          Adjust goal or scope
        </SaplingAction>
      ) : null}
    </div>
  );
}

const CATEGORY_LABEL: Record<string, string> = {
  syllabus: "Syllabus",
  lecture_notes: "Lecture notes",
  slides: "Slides",
  reading: "Reading",
  assignment: "Assignment",
  study_guide: "Study guide",
  other: "Other",
};

interface MaterialRow { id: string; file_name: string; category: string }
type MaterialsState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; rows: MaterialRow[] };

/** The course's real Library documents (GET /api/documents/user/{id}). A list
 *  to orient by, never a chat attachment or a citation; managing and reading
 *  them happens in Library. */
export function MaterialsContext({ userId, courseId, courseLabel }: { userId: string; courseId: string | null; courseLabel: string | null }) {
  const [state, setState] = useState<MaterialsState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!userId) return;
    let live = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a fresh load for this course
    setState({ status: "loading" });
    getDocuments(userId)
      .then((r) => {
        if (!live) return;
        const rows = ((r.documents ?? []) as { id: string; file_name: string; category: string; course_id: string | null }[])
          .filter((d) => courseId !== null && d.course_id === courseId)
          .map((d) => ({ id: d.id, file_name: d.file_name, category: d.category }));
        setState({ status: "ready", rows });
      })
      .catch((err) => {
        if (live) setState({ status: "error", message: humanizeError(err, "Couldn't load this course's materials.") });
      });
    return () => {
      live = false;
    };
  }, [userId, courseId, attempt]);

  return (
    <div className={styles.context} data-testid="tutor-materials">
      <p className={styles.contextLead}>Keep your sources close.</p>
      {state.status === "loading" && <StatusMessage tone="pending">Loading course materials…</StatusMessage>}
      {state.status === "error" && (
        <StatusMessage tone="error" testid="tutor-materials-error" onRetry={() => setAttempt((n) => n + 1)} retryLabel="Retry materials">
          {state.message}
        </StatusMessage>
      )}
      {state.status === "ready" && state.rows.length === 0 && (
        <p className={styles.muted} data-testid="tutor-materials-empty">
          No materials for {courseLabel ?? "this course"} yet. Upload them in Library and Clov can draw on them.
        </p>
      )}
      {state.status === "ready" && state.rows.length > 0 && (
        <ul className={styles.materials}>
          {state.rows.map((d) => (
            <li key={d.id} className={styles.material}>
              <BotanicalIcon name="paper" size={22} />
              <div>
                <p className={styles.materialName}>{d.file_name}</p>
                <p className={styles.muted}>
                  {[courseLabel, CATEGORY_LABEL[d.category] ?? "Document"].filter(Boolean).join(" · ")}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className={styles.muted}>Read and manage course materials in Library.</p>
      <Link href="/library" className={styles.primaryLink} data-testid="tutor-materials-library">
        Open course Library
      </Link>
    </div>
  );
}

/** The real knowledge map (original graph colours) and the concept the
 *  conversation is on. The full map lives on /tree. */
export function MapContext({
  graph,
  courseLabel,
  conceptCount,
  focusName,
  treeHref,
}: {
  graph: React.ReactNode;
  courseLabel: string | null;
  conceptCount: number;
  focusName: string | null;
  treeHref: string;
}) {
  return (
    <div className={styles.context} data-testid="tutor-map">
      <p className={styles.muted}>
        {[courseLabel, `${conceptCount} concept${conceptCount === 1 ? "" : "s"}`].filter(Boolean).join(" · ")}
      </p>
      {graph}
      <Link href={treeHref} className={styles.textLink} data-testid="tutor-map-full">
        Open the full knowledge map
      </Link>
      {focusName && (
        <section className={styles.focusCard}>
          <p className="sapling-eyebrow">Conversation focus</p>
          <p className={styles.focusName}>{focusName}</p>
        </section>
      )}
      <p className={styles.muted}>Checks provide learning evidence. Conversation keeps the ideas moving.</p>
    </div>
  );
}

// ── History ────────────────────────────────────────────────────────────────

type PastState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; rows: Session[] };

/** Open sessions resume where they left off; past (closed or legacy) sessions
 *  open read-only. Open = the loop's own list; past = GET /api/learn/sessions
 *  for this course, minus the open ones. */
export function TutorHistory({
  userId,
  courseId,
  open,
  currentId,
  onResume,
  onOpenPast,
  onNewSession,
}: {
  userId: string;
  courseId: string | null;
  open: LoopOpenSession[];
  currentId: string | null;
  onResume: (s: LoopOpenSession) => void;
  onOpenPast: (id: string) => void;
  onNewSession: () => void;
}) {
  const [query, setQuery] = useState("");
  const [past, setPast] = useState<PastState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const searchId = useId();
  useEffect(() => {
    if (!userId) return;
    let live = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a fresh read each time history opens
    setPast({ status: "loading" });
    getSessions(userId, 30)
      .then((r) => { if (live) setPast({ status: "ready", rows: r.sessions ?? [] }); })
      .catch((err) => { if (live) setPast({ status: "error", message: humanizeError(err, "Couldn't load past sessions.") }); });
    return () => {
      live = false;
    };
  }, [userId, attempt]);

  const q = query.trim().toLowerCase();
  const matches = (topic: string) => !q || topic.toLowerCase().includes(q);
  const openIds = useMemo(() => new Set(open.map((s) => s.session_id)), [open]);
  const openRows = open.filter((s) => matches(s.topic || "Session"));
  const pastRows = past.status === "ready"
    ? past.rows.filter((s) => s.course_id === courseId && !openIds.has(s.id) && matches(s.topic || "Session"))
    : [];

  return (
    <div className={styles.history} data-testid="tutor-history">
      <label htmlFor={searchId} className="sapling-visually-hidden">Search your sessions</label>
      <input
        id={searchId}
        type="search"
        className={styles.search}
        placeholder="Search your sessions"
        value={query}
        data-testid="tutor-history-search"
        onChange={(e) => setQuery(e.target.value)}
      />
      <section aria-labelledby={`${searchId}-open`} className={styles.historySection}>
        <h3 id={`${searchId}-open`} className={styles.historyHeading}>Open sessions</h3>
        {openRows.length === 0 ? (
          <p className={styles.muted}>{q ? "No open session matches." : "No open session in this course."}</p>
        ) : (
          <ul className={styles.historyList}>
            {openRows.map((s) => {
              const current = s.session_id === currentId;
              return (
                <li key={s.session_id}>
                  <button
                    type="button"
                    className={styles.historyRow}
                    data-open="true"
                    data-testid={`tutor-history-open-${s.session_id}`}
                    aria-current={current ? "true" : undefined}
                    onClick={() => onResume(s)}
                  >
                    <span className={styles.historyTopic}>{s.topic || "Session"}</span>
                    <span className={styles.historyMeta}>
                      {current ? "Current session" : `${PHASE_WORD[s.phase] ?? "Open"} · Resume where you left off`}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <section aria-labelledby={`${searchId}-past`} className={styles.historySection}>
        <h3 id={`${searchId}-past`} className={styles.historyHeading}>Past sessions</h3>
        {past.status === "loading" && <StatusMessage tone="pending">Loading past sessions…</StatusMessage>}
        {past.status === "error" && (
          <StatusMessage tone="error" testid="tutor-history-error" onRetry={() => setAttempt((n) => n + 1)} retryLabel="Retry past sessions">
            {past.message}
          </StatusMessage>
        )}
        {past.status === "ready" && pastRows.length === 0 && (
          <p className={styles.muted}>{q ? "No past session matches." : "No past sessions in this course yet."}</p>
        )}
        {pastRows.length > 0 && (
          <ul className={styles.historyList}>
            {pastRows.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className={styles.historyRow}
                  data-testid={`tutor-history-past-${s.id}`}
                  onClick={() => onOpenPast(s.id)}
                >
                  <span className={styles.historyTopic}>{s.topic || "Session"}</span>
                  <span className={styles.historyMeta}>
                    {s.ended_at ? "Closed" : "Earlier session"} · Read-only transcript
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <SaplingAction data-testid="tutor-history-new-session" onClick={onNewSession}>
        Start a new session
      </SaplingAction>
    </div>
  );
}

const PHASE_WORD: Record<string, string> = {
  probe: "Check-in",
  plan: "Plan",
  teach: "Learn",
  check: "Learn",
  feedback: "Learn",
};

// ── Welcome ────────────────────────────────────────────────────────────────

/** Shown only after session discovery succeeded and found no open session.
 *  Asking a question starts a guided session with it as the topic: Clov's
 *  opener answers it, then a short check-in finds where to begin. Picking a
 *  starter only fills the field. Nothing here grades. */
export function TutorWelcome({
  courseLabel,
  starting,
  onStartCheckIn,
  onAsk,
  materials,
}: {
  courseLabel: string | null;
  starting: boolean;
  onStartCheckIn: () => void;
  onAsk: (text: string) => void;
  materials: React.ReactNode;
}) {
  const [draft, setDraft] = useState("");
  const headingId = useId();
  const composerRef = useRef<HTMLDivElement>(null);
  const seed = (text: string) => {
    setDraft(text);
    const field = composerRef.current?.querySelector("textarea");
    if (field) {
      field.focus();
      field.setSelectionRange(text.length, text.length);
    }
  };
  return (
    <section className={styles.welcome} data-testid="tutor-welcome" aria-labelledby={headingId}>
      <BotanicalIcon name="clov" size={64} className={styles.welcomeMark} />
      <h1 id={headingId} className={styles.welcomeTitle}>What would you like to understand?</h1>
      <p className={styles.welcomeLead}>Ask a question, or let&apos;s find your next step.</p>
      <ul className={styles.starters} aria-label="Starting points">
        {STARTER_PROMPTS.map((p, i) => (
          <li key={p.label}>
            <button type="button" className={styles.starter} data-testid={`tutor-starter-${i}`} onClick={() => seed(p.seed)}>
              {p.label}
            </button>
          </li>
        ))}
      </ul>
      <section className={styles.planCard} aria-labelledby={`${headingId}-plan`}>
        <div className={styles.planCardText}>
          <h2 id={`${headingId}-plan`} className={styles.planCardTitle}>
            <BotanicalIcon name="learn" size={24} /> Learn with a plan
          </h2>
          <p className={styles.muted}>Start with a check-in, then approve your plan.</p>
        </div>
        <SaplingAction data-testid="tutor-welcome-start" disabled={starting} onClick={onStartCheckIn}>
          {starting ? "Starting…" : "Start check-in"}
        </SaplingAction>
      </section>
      <div ref={composerRef} className={styles.welcomeComposer}>
        <SaplingComposer
          testid="tutor-welcome-composer"
          value={draft}
          onChange={setDraft}
          onSend={(text) => onAsk(text)}
          state={starting ? "sending" : "idle"}
          canSend={!starting}
          label="Ask Clov about this course"
          placeholder={`Ask Clov about ${courseLabel ?? "this course"}…`}
          lead={materials}
        />
        <p className={styles.footnote}>
          A question starts a guided session: Clov answers, then a short check-in finds where to begin. Checks help
          choose what comes next.
        </p>
      </div>
    </section>
  );
}
