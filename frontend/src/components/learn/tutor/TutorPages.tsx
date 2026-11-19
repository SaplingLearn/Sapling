"use client";
import React, { useLayoutEffect, useRef } from "react";
import Link from "next/link";
import type { EnrolledCourse } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import { Icon } from "../../Icon";
import { ChevRight } from "./TutorIcons";
import { courseColor, sessionTitle, shortWhen, type TutorSessionRow } from "./sessions";
import styles from "./tutor.module.css";

/** Mastery as the map colours it: mastered / in progress / needs work / not started. */
export function masteryTone(score: number | null | undefined): string {
  if (score == null) return "var(--state-neutral)";
  if (score >= 0.75) return "var(--state-mastery)";
  if (score >= 0.45) return "var(--state-progress)";
  return "var(--state-struggle)";
}

export function Meter({ label, score, testId }: { label: string; score: number | null; testId?: string }) {
  const pct = score == null ? 0 : Math.round(Math.max(0, Math.min(1, score)) * 100);
  return (
    <div className={styles.meter} data-testid={testId}>
      <span title={label}>{label}</span>
      <span
        className={styles.bar}
        role="meter"
        aria-label={`${label} skill`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        <i style={{ width: `${pct}%`, background: masteryTone(score) }} />
      </span>
      <span className={styles.pct}>{score == null ? "—" : `${pct}%`}</span>
    </div>
  );
}

/** A page's heading takes focus when the page replaces another (spec §13 A135). */
function useFocusHeading<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useLayoutEffect(() => {
    if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
    ref.current?.focus({ preventScroll: true });
  }, []);
  return ref;
}

/** T1 · Tutor home: where a new session starts. */
export function TutorHome({
  courseName,
  continueRow,
  continueTitle,
  dueCount,
  dueHref,
  startWith,
  busy,
  closesCurrent,
  onContinue,
  onStart,
  onStartWith,
  onGoal,
}: {
  courseName: string | null;
  /** The course's open session, offered as "Continue". */
  continueRow: TutorSessionRow | null;
  /** Its name as the rest of the shell shows it (the course decides it). */
  continueTitle?: string;
  /** Reviews due now in every course (the review queue's count); null: unknown. */
  dueCount: number | null;
  /** Where "Review what's due" goes; null while `hide_study` hides Study. */
  dueHref: string | null;
  /** The weakest concept the map knows, offered as a first focus. */
  startWith: string | null;
  busy: boolean;
  /** Starting wraps up the open session first (one open session per course). */
  closesCurrent: string | null;
  onContinue: () => void;
  onStart: () => void;
  onStartWith: (concept: string) => void;
  onGoal: () => void;
}) {
  const heading = useFocusHeading<HTMLHeadingElement>();
  return (
    <div className={styles.home} data-testid="tutor-home">
      <span className={styles.heroMark} aria-hidden>
        <Icon name="clover" size={28} />
      </span>
      <h2 ref={heading} tabIndex={-1}>What do you want to learn today?</h2>
      <p className={styles.quote}>
        Your tutor checks what you know, builds a plan, then teaches and checks one concept at a time
        {courseName ? ` in ${courseName}` : ""}.
      </p>
      <div className={styles.suggest}>
        {continueRow && (
          <button type="button" className={styles.pill} data-testid="tutor-home-continue" onClick={onContinue} disabled={busy}>
            Continue: {continueTitle ?? sessionTitle(continueRow)}
          </button>
        )}
        {dueHref && (dueCount ?? 0) > 0 && (
          <Link className={styles.pill} data-testid="tutor-home-due" href={dueHref}>
            Review what&apos;s due · {dueCount}
          </Link>
        )}
        {startWith && (
          <button type="button" className={styles.pill} data-testid="tutor-home-start-with" onClick={() => onStartWith(startWith)} disabled={busy}>
            Start with {startWith}
          </button>
        )}
        <button type="button" className={styles.pill} data-testid="tutor-home-goal" onClick={onGoal} disabled={busy}>
          Set a goal
        </button>
      </div>
      <button
        type="button"
        data-testid="loop-start-guided"
        className={`btn btn--primary ${styles.cta}`}
        onClick={onStart}
        disabled={busy}
      >
        <Icon name="sparkle" size={14} /> {busy ? "Starting…" : "Start a guided session"}
      </button>
      {closesCurrent && (
        <p className={styles.ctaNote}>
          Starting wraps up “{closesCurrent}” first.
        </p>
      )}
    </div>
  );
}

type Material = { id: string; file_name: string; category?: string | null };

/** A list that could not be read says so, with a retry — never its empty state. */
export function LoadFailed({ what, onRetry, testId }: { what: string; onRetry: () => void; testId?: string }) {
  return (
    <div role="status" data-testid={testId} className={`${styles.listRow} ${styles.listRowStatic}`} style={{ gap: 10, flexWrap: "wrap" }}>
      <span className={styles.ls}>Couldn&apos;t load {what}.</span>
      <button type="button" className="btn btn--sm" onClick={onRetry}>Try again</button>
    </div>
  );
}

/** T2 · A course, like a Claude project: its sessions, progress and material. */
export function TutorCourse({
  course,
  sessions,
  concepts,
  materials,
  dueHref,
  libraryHref,
  onRetrySessions,
  onRetryMaterials,
  onOpen,
  onAll,
}: {
  course: EnrolledCourse;
  sessions: TutorSessionRow[];
  concepts: GraphNode[];
  materials: Material[] | null;
  /** Null while `hide_study` hides Study. */
  dueHref: string | null;
  /** Where material is added; null while `hide_library` hides the Library. */
  libraryHref: string | null;
  /** Present when the session list failed to load (never "No sessions yet"). */
  onRetrySessions?: (() => void) | null;
  /** Present when the material failed to load (never "No material yet"). */
  onRetryMaterials?: (() => void) | null;
  onOpen: (row: TutorSessionRow) => void;
  onAll: () => void;
}) {
  const heading = useFocusHeading<HTMLHeadingElement>();
  const recent = sessions.slice(0, 3);
  const progress = [...concepts]
    .sort((a, b) => Date.parse(b.last_studied_at || "0") - Date.parse(a.last_studied_at || "0") || b.mastery_score - a.mastery_score)
    .slice(0, 6);
  return (
    <div className={styles.page} data-testid="tutor-course-page" data-course-id={course.course_id}>
      <div className={styles.grid2}>
        <section className="card">
          <div className={styles.cardHead}>
            <div>
              <span className="label-micro">Sessions in this course</span>
              <h3 className="h-serif">{sessions.length} {sessions.length === 1 ? "session" : "sessions"}</h3>
            </div>
            <button type="button" className={styles.textLink} onClick={onAll}>All sessions <ChevRight /></button>
          </div>
          {recent.length > 0 ? recent.map((s) => (
            <button key={s.id} type="button" className={styles.listRow} onClick={() => onOpen(s)}>
              <span className={`${styles.sdot} ${s.open ? styles.sdotOn : ""}`} aria-hidden />
              <span className={styles.grow}>
                <div className={styles.lt}>{sessionTitle(s, course)}</div>
                <div className={styles.ls}>{shortWhen(s.startedAt)} · {s.open ? "in progress" : "wrapped up"}</div>
              </span>
              <ChevRight />
            </button>
          )) : !onRetrySessions && (
            <div className={`${styles.listRow} ${styles.listRowStatic}`}><span className={styles.ls}>No sessions yet.</span></div>
          )}
          {onRetrySessions && <LoadFailed testId="tutor-course-sessions-error" what="your past sessions" onRetry={onRetrySessions} />}
        </section>
        <section className="card">
          <div className={styles.cardHead}>
            <div>
              <span className="label-micro">Your progress</span>
              <h3 ref={heading} tabIndex={-1} className="h-serif">{concepts.length} {concepts.length === 1 ? "concept" : "concepts"}</h3>
            </div>
          </div>
          <div className={styles.cardPad}>
            {progress.length > 0
              ? progress.map((n) => <Meter key={n.id} label={n.name} score={n.mastery_tier === "unexplored" ? null : n.mastery_score} />)
              : <p className={styles.ls} style={{ margin: 0 }}>Concepts appear here as you learn.</p>}
            {dueHref && <Link href={dueHref} className="btn btn--sm" style={{ alignSelf: "flex-start" }}>Review what&apos;s due</Link>}
          </div>
        </section>
      </div>
      <section className="card">
        <div className={styles.cardHead}>
          <div>
            <span className="label-micro">Course material</span>
            <h3 className="h-serif">
              {materials !== null ? `${materials.length} ${materials.length === 1 ? "file" : "files"}` : onRetryMaterials ? "Not loaded" : "Loading…"}
            </h3>
          </div>
          {libraryHref && <Link href={libraryHref} className="btn btn--sm"><Icon name="up" size={13} /> Add material</Link>}
        </div>
        {onRetryMaterials && <LoadFailed testId="tutor-course-materials-error" what="this course's material" onRetry={onRetryMaterials} />}
        {(materials ?? []).slice(0, 6).map((m) => (
          <div key={m.id} className={`${styles.listRow} ${styles.listRowStatic}`}>
            <Icon name="doc" size={15} />
            <span className={styles.grow}>
              <div className={styles.lt} style={{ fontWeight: 500 }}>{m.file_name}</div>
              {m.category && <div className={styles.ls}>{m.category.replace(/_/g, " ")}</div>}
            </span>
          </div>
        ))}
        {materials !== null && materials.length === 0 && (
          <div className={`${styles.listRow} ${styles.listRowStatic}`}>
            <span className={styles.ls}>
              {libraryHref ? "No material yet — upload notes or slides so the tutor can quiz you on them." : "No material yet."}
            </span>
          </div>
        )}
      </section>
    </div>
  );
}

type Filter = "all" | "open" | "done";
const FILTERS: [Filter, string][] = [["all", "All"], ["open", "In progress"], ["done", "Wrapped up"]];

/** T3 · Every session, newest first, with search and a status filter. */
export function TutorAllSessions({
  sessions,
  courses,
  query,
  setQuery,
  filter,
  setFilter,
  onRetry,
  onOpen,
}: {
  sessions: TutorSessionRow[];
  courses: EnrolledCourse[];
  query: string;
  setQuery: (q: string) => void;
  filter: Filter;
  setFilter: (f: Filter) => void;
  /** Present when the session list failed to load: the rows may be incomplete. */
  onRetry?: (() => void) | null;
  onOpen: (row: TutorSessionRow) => void;
}) {
  const search = useFocusHeading<HTMLInputElement>();
  const byId = new Map(courses.map((c, i) => [c.course_id, { c, i }]));
  const q = query.trim().toLowerCase();
  const rows = sessions.filter((s) => {
    if (filter === "open" && !s.open) return false;
    if (filter === "done" && s.open) return false;
    return !q || sessionTitle(s, byId.get(s.courseId ?? "")?.c).toLowerCase().includes(q);
  });
  return (
    <div className={styles.page} data-testid="tutor-all-sessions">
      <div className={styles.toolbar}>
        <label className={`${styles.search} ${styles.grow}`} style={{ maxWidth: 420 }}>
          <Icon name="search" size={14} />
          <input ref={search} type="search" placeholder="Search sessions" aria-label="Search all sessions" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <div role="group" aria-label="Filter sessions" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {FILTERS.map(([k, l]) => (
            <button key={k} type="button" className={styles.segPill} aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>
          ))}
        </div>
      </div>
      <section className="card">
        {rows.map((s) => {
          const entry = byId.get(s.courseId ?? "");
          return (
            <button key={s.id} type="button" className={styles.listRow} onClick={() => onOpen(s)}>
              <span className={styles.cdot} style={{ background: courseColor(entry?.c, entry?.i ?? 0) }} aria-hidden />
              <span className={styles.grow}>
                <div className={styles.lt}>{sessionTitle(s, entry?.c)}</div>
                <div className={styles.ls}>
                  {entry?.c.course_code && <span style={{ fontFamily: "var(--font-mono)" }}>{entry.c.course_code} · </span>}
                  {shortWhen(s.startedAt)}
                </div>
              </span>
              <span className={s.open ? "chip chip--accent" : "chip"}>{s.open ? "In progress" : "Wrapped up"}</span>
            </button>
          );
        })}
        {rows.length === 0 && !onRetry && (
          <div className={`${styles.listRow} ${styles.listRowStatic}`}><span className={styles.ls}>No sessions match.</span></div>
        )}
        {onRetry && <LoadFailed testId="tutor-all-sessions-error" what="your past sessions" onRetry={onRetry} />}
      </section>
    </div>
  );
}
export type { Filter as SessionFilter };
