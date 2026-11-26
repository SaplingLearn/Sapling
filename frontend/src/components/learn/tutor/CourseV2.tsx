"use client";
// The Tutor's course page, rebuilt (Tutor redesign phase 4, behind
// `course_page_v2`; design: learn/__fixtures__/course.design.html, the Claude
// Design board). One note on top when something is due, then two columns:
// "Ready to learn" (the concepts whose prerequisites are already strong, each
// with its level and Learn) and "Sessions" on the left; "Coming up" (the
// course's upcoming assignments) and "Materials" on the right.
//
// "Ready to learn" mirrors the planner's outer fringe (`learning/planner.py`),
// more strictly: a concept is listed only while every direct prerequisite is
// Proficient, so a prerequisite cycle hides a concept rather than vouching for
// it. The board's readiness bar on each Coming-up row, its review minutes and
// its Library column (study guides, flashcards, practice exams) have nothing
// behind them on this page yet and are not built.
import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { HandoffLink } from "@/components/ui/HandoffLink";
import { useUser } from "@/context/UserContext";
import { retentionHref } from "@/context/RetentionDueContext";
import { getFlashcards, getUpcomingAssignments, type Assignment, type EnrolledCourse, type LoopGoal } from "@/lib/api";
import { listGuides } from "@/lib/studyGuide/api";
import type { GuideCard } from "@/lib/studyGuide/types";
import { flashcardsHref } from "@/lib/toolHrefs";
import { cardsOfCourse, type FlashcardRow } from "../../study/hubModel";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { LEARNING_COPY, plural } from "@/lib/learningCopy";
import { carriesSkill, tierWord } from "@/lib/levels";
import { Icon } from "../../Icon";
import { useFlag } from "@/context/FlagsContext";
import { LoadFailed, TutorCourse, masteryTone, meterTier } from "./TutorPages";
import { CourseSetup, SETUP_COPY } from "./CourseSetup";
import { MilestonePage } from "./MilestonePage";
import { coveredConcepts, readinessOf, useMilestoneConcepts, useMilestones } from "./milestones";
import { sessionTitle, shortWhen, type TutorSessionRow } from "./sessions";
import tutorStyles from "./tutor.module.css";
import styles from "./CourseV2.module.css";

export const COURSE_COPY = {
  ready: "Ready to learn",
  readyLine: "You know what these build on.",
  readyNone: "Concepts appear here as you learn.",
  sessions: "Sessions",
  allSessions: "All sessions",
  noSessions: "No sessions yet.",
  comingUp: "Coming up",
  nothingUp: "Nothing coming up.",
  materials: "Materials",
  upload: "Upload",
  noMaterials: "No material yet. Upload notes or slides so the tutor can teach from them.",
  retention: "A retention check is ready for this course.",
  startCheck: "Start check",
  open: "Open",
  learn: "Learn",
  library: "Library",
  studyGuide: "Study guide",
  flashcards: "Flashcards",
} as const;

const READY_MAX = 5;

const score = (n: GraphNode): number | null => (n.mastery_tier === "unexplored" ? null : n.mastery_score);

export type ReadyConcept = { id: string; name: string; score: number | null; hasPrereqs: boolean };

/** The course's ready concepts, strongest first (the planner's order): below
 *  Proficient, with every direct prerequisite (a `prerequisite` edge's source)
 *  Proficient. */
export function readyConcepts(nodes: readonly GraphNode[], edges: readonly GraphEdge[], max = READY_MAX): ReadyConcept[] {
  const ladder = nodes.some(carriesSkill);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const proficient = (n: GraphNode | undefined) => !!n && meterTier(score(n), ladder) === "mastered";
  const prereqs = new Map<string, string[]>();
  for (const e of edges) {
    if (e.relationship_type !== "prerequisite" || e.source === e.target) continue;
    prereqs.set(e.target, [...(prereqs.get(e.target) ?? []), e.source]);
  }
  return nodes
    .filter((n) => !n.is_subject_root && !proficient(n))
    .filter((n) => (prereqs.get(n.id) ?? []).every((p) => proficient(byId.get(p))))
    .sort((a, b) => (score(b) ?? -1) - (score(a) ?? -1))
    .slice(0, max)
    .map((n) => ({ id: n.id, name: n.name, score: score(n), hasPrereqs: (prereqs.get(n.id) ?? []).length > 0 }));
}

/** A due date's calendar day, local: a bare `YYYY-MM-DD` is that day, not UTC midnight. */
function dueDay(iso: string): Date | null {
  const bare = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const d = bare ? new Date(Number(bare[1]), Number(bare[2]) - 1, Number(bare[3])) : new Date(iso);
  return Number.isNaN(d.getTime()) ? null : new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** "Dec 2, in 6 days" / "Dec 2, tomorrow" / "Dec 2, today"; null when past or unreadable. */
export function dueWhen(iso: string | null, now: Date = new Date()): string | null {
  const day = iso ? dueDay(iso) : null;
  if (!day) return null;
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((day.getTime() - today.getTime()) / 86_400_000);
  if (days < 0) return null;
  const date = day.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return `${date}, ${days === 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`}`;
}

/** The course's upcoming assignments, soonest first (the Dashboard's read). */
export function useCourseUpcoming(courseId: string) {
  const { userId } = useUser();
  const [state, setState] = useState<{ items: Assignment[] | null; failed: boolean }>({ items: null, failed: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!userId) return;
    let live = true;
    getUpcomingAssignments(userId)
      .then((r) => { if (live) setState({ items: r.assignments ?? [], failed: false }); })
      .catch(() => { if (live) setState({ items: null, failed: true }); });
    return () => { live = false; };
  }, [userId, attempt]);
  const retry = useCallback(() => { setState({ items: null, failed: false }); setAttempt((a) => a + 1); }, []);
  const items = (state.items ?? [])
    .filter((a) => a.course_id === courseId && dueWhen(a.due_date) !== null)
    .sort((a, b) => (dueDay(a.due_date ?? "")?.getTime() ?? 0) - (dueDay(b.due_date ?? "")?.getTime() ?? 0))
    .slice(0, 4);
  return { items: state.items === null ? null : items, failed: state.failed, retry };
}

/** The course's Library (the board's column): its study guides and how many
 *  flashcards it has, read as the Study hub reads them; nothing while Study
 *  is hidden (both reads are Study's). */
export function useCourseLibrary(courseId: string, enabled: boolean) {
  const { userId } = useUser();
  const [lib, setLib] = useState<{ courseId: string; guides: GuideCard[]; cards: number } | null>(null);
  useEffect(() => {
    if (!enabled || !userId) return;
    let live = true;
    Promise.all([
      listGuides(userId).then((r) => r.guides ?? []).catch(() => [] as GuideCard[]),
      getFlashcards(userId).then((r) => (r.flashcards ?? []) as FlashcardRow[]).catch(() => [] as FlashcardRow[]),
    ]).then(([guides, cards]) => {
      if (live) setLib({ courseId, guides: guides.filter((g) => g.course_id === courseId), cards: cardsOfCourse(cards, courseId).length });
    });
    return () => { live = false; };
  }, [userId, courseId, enabled]);
  return lib && lib.courseId === courseId ? lib : null;
}

type Material = { id: string; file_name: string; category?: string | null };

/** Coming up: the course's next dated work; with `milestones` each row opens
 *  its milestone, with `course_setup` the head opens the course setup. */
function ComingUp({ courseId, readyFor, onMilestone, onSetup }: {
  courseId: string;
  readyFor?: ReadonlyMap<string, string | null> | null;
  onMilestone?: (id: string) => void;
  onSetup?: () => void;
}) {
  const upcoming = useCourseUpcoming(courseId);
  return (
    <section aria-labelledby="tutor-course-coming" className={styles.section}>
      <div className={styles.head}>
        <h2 id="tutor-course-coming" className={`h-serif ${styles.h2}`}>{COURSE_COPY.comingUp}</h2>
        {onSetup && <button type="button" className={styles.rowLink} onClick={onSetup} data-testid="tutor-course-setup">{SETUP_COPY.entry}</button>}
      </div>
      {upcoming.failed ? <LoadFailed testId="tutor-course-upcoming-error" what="what's coming up" onRetry={upcoming.retry} />
        : upcoming.items === null ? null : upcoming.items.length > 0 ? (
          <ul className={styles.box}>
            {upcoming.items.map((a) => {
              const ready = readyFor?.get(a.id) ?? null;
              const body = (
                <>
                  <span className={styles.name}>{a.title}</span>
                  {ready && <span className={styles.dim} data-testid={`tutor-course-due-ready-${a.id}`}>{ready}</span>}
                  <span className={styles.dim}>{dueWhen(a.due_date)}</span>
                </>
              );
              return onMilestone ? (
                <li key={a.id} data-testid={`tutor-course-due-${a.id}`}>
                  <button type="button" className={styles.sessionRow} onClick={() => onMilestone(a.id)}>{body}</button>
                </li>
              ) : (
                <li key={a.id} className={styles.dueRow} data-testid={`tutor-course-due-${a.id}`}>{body}</li>
              );
            })}
          </ul>
        ) : <p className={styles.sub}>{COURSE_COPY.nothingUp}</p>}
    </section>
  );
}

export function CourseV2({
  course, sessions, concepts, edges, materials, retentionDue, dueCount, dueHref, reviewInSidebar, libraryHref,
  onRetrySessions, onRetryMaterials, onRetryConcepts, onOpen, onAll, onLearn, onMilestone, readyFor, onSetup,
}: {
  course: EnrolledCourse;
  sessions: TutorSessionRow[];
  concepts: GraphNode[];
  edges: GraphEdge[];
  materials: Material[] | null;
  /** A retention check is due in this course (RetentionDueContext). */
  retentionDue: boolean;
  /** Reviews due in every course; null unknown. */
  dueCount: number | null;
  dueHref: string | null;
  /** `session_v2`: the sidebar's Review already says the count (CourseSlot reads it). */
  reviewInSidebar?: boolean;
  libraryHref: string | null;
  onRetrySessions?: (() => void) | null;
  onRetryMaterials?: (() => void) | null;
  onRetryConcepts?: (() => void) | null;
  onOpen: (row: TutorSessionRow) => void;
  onAll: () => void;
  onLearn: (concept: { id: string; name: string }) => void;
  /** `milestones`: a Coming-up row opens that milestone's page. */
  onMilestone?: (id: string) => void;
  /** `milestones`: "3 of 8 ready" per milestone with concepts linked to it. */
  readyFor?: ReadonlyMap<string, string | null> | null;
  /** `course_setup`: open the course setup (Coming up's head). */
  onSetup?: () => void;
}) {
  // spec §13 A135: the page replaces what was on screen, so its first heading takes focus.
  const heading = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
    heading.current?.focus({ preventScroll: true });
  }, []);
  const ladder = concepts.some(carriesSkill);
  const ready = readyConcepts(concepts, edges);
  const studyShown = useFlag("hide_study") !== "on";
  const library = useCourseLibrary(course.course_id, studyShown);
  const recent = sessions.slice(0, 4);
  const showReview = !reviewInSidebar && !!dueHref && (dueCount ?? 0) > 0; // each fact once
  return (
    <div className={styles.page} data-testid="tutor-course-page" data-course-id={course.course_id}>
      <div className={styles.col} data-testid="tutor-course-v2">
        {retentionDue ? (
          <div className={styles.note} data-testid="tutor-course-retention">
            <span className={styles.noteText}>{COURSE_COPY.retention}</span>
            <HandoffLink variant="plain" href={retentionHref([course.course_id])} className={styles.noteLink}>{COURSE_COPY.startCheck}</HandoffLink>
          </div>
        ) : showReview && (
          <div className={styles.note} data-testid="tutor-course-review">
            <span className={styles.noteText}>{LEARNING_COPY.reviewsDue(dueCount ?? 0)}</span>
            <HandoffLink variant="plain" href={dueHref!} className={styles.noteLink}>{LEARNING_COPY.review}</HandoffLink>
          </div>
        )}
        <div className={styles.grid}>
          <div className={styles.stack}>
            <section aria-labelledby="tutor-course-ready" className={styles.section}>
              <h2 id="tutor-course-ready" ref={heading} tabIndex={-1} className={`h-serif ${styles.h2}`}>{COURSE_COPY.ready}</h2>
              {ready.length > 0 && ready.every((c) => c.hasPrereqs) && <p className={styles.sub}>{COURSE_COPY.readyLine}</p>}
              {onRetryConcepts ? <LoadFailed testId="tutor-course-concepts-error" what="your concepts" onRetry={onRetryConcepts} /> : ready.length > 0 ? (
                <ul className={styles.box}>
                  {ready.map((c) => {
                    const tier = meterTier(c.score, ladder);
                    const word = tierWord(tier, ladder);
                    const pct = c.score == null ? 0 : Math.round(Math.max(0, Math.min(1, c.score)) * 100);
                    return (
                      <li key={c.id} className={styles.readyRow} data-testid={`tutor-course-ready-${c.id}`} data-tier={tier}>
                        <span className={styles.name}>{c.name}</span>
                        <span className={tutorStyles.bar} role="meter" aria-label={`${c.name} skill`} aria-valuetext={word}
                          aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
                          {c.score != null && <i style={{ "--fill": `${pct}%`, "--tone": masteryTone(c.score, ladder) } as React.CSSProperties} />}
                        </span>
                        <span className={styles.dim}>{word}</span>
                        <button type="button" className={styles.rowLink} data-testid={`tutor-course-learn-${c.id}`}
                          aria-label={`${COURSE_COPY.learn} ${c.name}`} onClick={() => onLearn({ id: c.id, name: c.name })}>
                          {COURSE_COPY.learn}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : <p className={styles.sub}>{COURSE_COPY.readyNone}</p>}
            </section>
            <section aria-labelledby="tutor-course-sessions" className={styles.section}>
              <div className={styles.head}>
                <h2 id="tutor-course-sessions" className={`h-serif ${styles.h2}`}>{COURSE_COPY.sessions}</h2>
                <button type="button" className={styles.rowLink} onClick={onAll}>{COURSE_COPY.allSessions}</button>
              </div>
              {onRetrySessions ? <LoadFailed testId="tutor-course-sessions-error" what="your past sessions" onRetry={onRetrySessions} /> : recent.length > 0 ? (
                <ul className={styles.box}>
                  {recent.map((s) => (
                    <li key={s.id}>
                      <button type="button" className={styles.sessionRow} onClick={() => onOpen(s)} data-testid={`tutor-course-session-${s.id}`}>
                        <span className={`${tutorStyles.sdot} ${s.open ? tutorStyles.sdotOn : ""}`} aria-hidden />
                        <span className={styles.name}>{sessionTitle(s, course)}</span>
                        {s.open ? <span className={styles.open}>{COURSE_COPY.open}</span> : <span className={styles.dim}>{shortWhen(s.startedAt)}</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : <p className={styles.sub}>{COURSE_COPY.noSessions}</p>}
            </section>
          </div>
          <div className={styles.stack}>
            <ComingUp courseId={course.course_id} readyFor={readyFor} onMilestone={onMilestone} onSetup={onSetup} />
            <section aria-labelledby="tutor-course-materials" className={styles.section}>
              <div className={styles.head}>
                <h2 id="tutor-course-materials" className={`h-serif ${styles.h2}`}>{COURSE_COPY.materials}</h2>
                {libraryHref && <Link href={libraryHref} className={styles.rowLink}><Icon name="up" size={13} /> {COURSE_COPY.upload}</Link>}
              </div>
              {onRetryMaterials ? <LoadFailed testId="tutor-course-materials-error" what="this course's material" onRetry={onRetryMaterials} />
                : materials === null ? null : materials.length > 0 ? (
                  <ul className={styles.box}>
                    {materials.slice(0, 6).map((m) => (
                      <li key={m.id} className={styles.dueRow}>
                        <span className={styles.name}>{m.file_name}</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className={styles.sub}>{libraryHref ? COURSE_COPY.noMaterials : "No material yet."}</p>}
            </section>
            {library && (library.guides.length > 0 || library.cards > 0) && (
              <section aria-labelledby="tutor-course-library" className={styles.section} data-testid="tutor-course-library">
                <h2 id="tutor-course-library" className={`h-serif ${styles.h2}`}>{COURSE_COPY.library}</h2>
                <ul className={styles.box}>
                  {library.guides.slice(0, 3).map((g) => (
                    <li key={g.id} className={styles.dueRow}>
                      <Link href={`/study/guide/${g.id}`} className={styles.name} data-testid={`tutor-course-guide-${g.id}`}>{g.title}</Link>
                      <span className={styles.dim}>{COURSE_COPY.studyGuide}</span>
                    </li>
                  ))}
                  {library.cards > 0 && (
                    <li className={styles.dueRow}>
                      <Link href={flashcardsHref(course.course_id)} className={styles.name} data-testid="tutor-course-flashcards">{COURSE_COPY.flashcards}</Link>
                      <span className={styles.dim}>{plural(library.cards, "card")}</span>
                    </li>
                  )}
                </ul>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** The course view: the rebuilt page with `course_page_v2` on, else the page
 *  as before (the flag reads live here, out of LoopLearn). */
export function CourseSlot({ milestoneId = null, onMilestone, onStartGoal, onStartCourse, onConceptsChanged, ...props }: React.ComponentProps<typeof CourseV2> & {
  /** `milestones`: the milestone on screen, else the course page. */
  milestoneId?: string | null;
  onMilestone?: (id: string | null) => void;
  onStartGoal?: (topic: string, goal: LoopGoal) => void;
  /** `course_setup`: the Done step's Start learning (a course session). */
  onStartCourse?: () => void;
  /** `course_setup`: re-read the graph after the setup changed the course's concepts. */
  onConceptsChanged?: () => Promise<void> | void;
}) {
  const v2 = useFlag("course_page_v2") === "on";
  const setupOn = useFlag("course_setup") === "on" && v2 && !!onStartCourse && !!onConceptsChanged;
  const [setupFor, setSetupFor] = useState<string | null>(null);
  const reviewInSidebar = useFlag("session_v2") === "on";
  const milestonesOn = useFlag("milestones") === "on";
  const ms = useMilestones(milestonesOn);
  const conceptsBy = useMilestoneConcepts(props.course.course_id, ms.items, milestonesOn);
  if (setupOn && setupFor === props.course.course_id) {
    return <CourseSetup course={props.course} concepts={props.concepts} hasMaterials={!!props.materials?.length}
      onClose={() => setSetupFor(null)} onStart={() => { setSetupFor(null); onStartCourse!(); }} onConceptsChanged={onConceptsChanged!} />;
  }
  if (milestonesOn && milestoneId && onMilestone && onStartGoal) {
    const current = ms.items?.find((m) => m.id === milestoneId && m.courseId === props.course.course_id);
    if (current) {
      return <MilestonePage course={props.course} milestone={current} conceptIds={conceptsBy?.get(current.id) ?? null}
        nodes={props.concepts} sessions={props.sessions} onBack={() => onMilestone(null)} onOpen={props.onOpen}
        onLearn={props.onLearn} onStartGoal={onStartGoal} />;
    }
    if (ms.items === null && !ms.failed) return <div className={styles.page} aria-busy="true" data-testid="tutor-milestone-pending" />;
  }
  const readyFor = milestonesOn && conceptsBy ? new Map([...conceptsBy].map(([id, ids]) => {
    const r = readinessOf(coveredConcepts(ids, props.concepts));
    return [id, r.total ? `${r.ready} of ${r.total} ready` : null] as const;
  })) : null;
  if (v2) {
    return <CourseV2 {...props} reviewInSidebar={reviewInSidebar} readyFor={readyFor}
      onMilestone={milestonesOn && onMilestone ? (id) => onMilestone(id) : undefined}
      onSetup={setupOn ? () => setSetupFor(props.course.course_id) : undefined} />;
  }
  const { edges: _e, retentionDue: _r, dueCount: _d, reviewInSidebar: _s, onLearn: _l, readyFor: _f, onSetup: _u, ...old } = props;
  return <TutorCourse {...old} />;
}
