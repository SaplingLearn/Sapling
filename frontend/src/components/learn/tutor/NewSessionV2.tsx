"use client";
// New session, rebuilt (Tutor redesign phase 4, behind `new_session_v2`;
// design: learn/__fixtures__/new-session.design.html, the Claude Design
// board). One question, "What are we working on?", one choice per kind of
// session as a radio card (a title and one line each), ONE start button that
// names the picked choice, and one line when starting wraps up the open
// session. The choices are the ones the Tutor can start today: continue the
// open session, learn the concept the map suggests, a whole-course session,
// work toward a goal (the goal editor), and review what's due (Study). The
// board's "Just ask a question" has no ungraded session behind it yet and its
// "Prepare for Midterm 2" waits for milestones; neither is offered.
import React, { useId, useLayoutEffect, useRef, useState } from "react";
import { HandoffLink } from "@/components/ui/HandoffLink";
import { LEARNING_COPY, plural } from "@/lib/learningCopy";
import { useFlag } from "@/context/FlagsContext";
import type { LoopGoal } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import { coveredConcepts, prepareGoal, useMilestoneConcepts, useMilestones } from "./milestones";
import styles from "./NewSessionV2.module.css";

export const NEW_SESSION_COPY = {
  title: "What are we working on?",
  legend: "Kind of session",
  continueLine: "Pick up where you stopped.",
  conceptLine: "Starts with a short check-in on it.",
  courseTitle: (course: string | null) => (course ? `Work through ${course}` : "Work through this course"),
  courseLine: "Starts with a short check-in, then a plan.",
  goalTitle: "Work toward a goal",
  goalLine: "Say what you want to learn and pick its concepts.",
  askTitle: "Just ask a question",
  askLine: "Talk it through. Nothing is graded.",
  wrapsUp: (title: string) => `This wraps up your open session, ${title}.`,
} as const;

export type IntentId = "prepare" | "continue" | "concept" | "course" | "goal" | "review" | "ask";
export type Intent = { id: IntentId; title: string; line: string; label: string; startsNew: boolean };

/** The choices, in the order the board lists them (what's already going
 *  first, then new learning, a goal, and review last). */
export function intentsFor({ prepare = null, ask = false, continueTitle, startWith, courseName, dueCount, dueHref }: {
  /** `just_ask`: offer an ungraded chat. */
  ask?: boolean;
  /** `milestones`: the course's next exam with concepts linked to it. */
  prepare?: { title: string; concepts: number } | null;
  continueTitle: string | null;
  startWith: { id: string; name: string } | null;
  courseName: string | null;
  dueCount: number | null;
  dueHref: string | null;
}): Intent[] {
  const out: Intent[] = [];
  if (prepare) out.push({ id: "prepare", title: `Prepare for ${prepare.title}`, line: `${plural(prepare.concepts, "concept")}. Starts with a short check-in.`, label: "Start preparing", startsNew: true });
  if (continueTitle) out.push({ id: "continue", title: LEARNING_COPY.continueSession(continueTitle), line: NEW_SESSION_COPY.continueLine, label: "Continue", startsNew: false });
  if (startWith) out.push({ id: "concept", title: LEARNING_COPY.learnConcept(startWith.name), line: NEW_SESSION_COPY.conceptLine, label: "Start learning", startsNew: true });
  out.push({ id: "course", title: NEW_SESSION_COPY.courseTitle(courseName), line: NEW_SESSION_COPY.courseLine, label: LEARNING_COPY.newSession, startsNew: true });
  out.push({ id: "goal", title: NEW_SESSION_COPY.goalTitle, line: NEW_SESSION_COPY.goalLine, label: "Choose a goal", startsNew: true });
  // The glossary's words (lib/learningCopy.ts), not the board's retired "Review what's due" / "Start review".
  if (ask) out.push({ id: "ask", title: NEW_SESSION_COPY.askTitle, line: NEW_SESSION_COPY.askLine, label: "Start chatting", startsNew: true });
  if (dueHref && (dueCount ?? 0) > 0) out.push({ id: "review", title: LEARNING_COPY.review, line: `${LEARNING_COPY.reviewsDue(dueCount ?? 0)}.`, label: LEARNING_COPY.review, startsNew: false });
  return out;
}

/** The choice picked first: a whole-course session, as the old home's one CTA. */
export const DEFAULT_INTENT: IntentId = "course";

/** `milestones`: the course's next exam or quiz with concepts linked to it,
 *  and the goal its "Prepare" starts (its concepts not ready yet). */
function usePrepare(courseId: string | null, nodes: readonly GraphNode[]) {
  const on = useFlag("milestones") === "on" && !!courseId;
  const { items } = useMilestones(on);
  const conceptsBy = useMilestoneConcepts(courseId, items, on);
  if (!on || !items || !conceptsBy) return null;
  for (const m of items.filter((x) => x.courseId === courseId && x.type !== "Homework")) {
    const concepts = coveredConcepts(conceptsBy.get(m.id) ?? [], nodes);
    const plan = prepareGoal(m, concepts);
    if (plan) return { title: m.title, concepts: concepts.length, plan };
  }
  return null;
}

export function NewSessionV2({
  courseName, continueTitle, startWith, dueCount, dueHref, busy, starting, closesCurrent,
  onContinue, onStart, onStartWith, onGoal, courseId = null, nodes = [], onStartGoal, onAsk,
}: {
  courseName: string | null;
  /** The course's open session's name, offered as "Continue …"; null: none. */
  continueTitle: string | null;
  startWith: { id: string; name: string } | null;
  dueCount: number | null;
  dueHref: string | null;
  busy: boolean;
  starting: boolean;
  closesCurrent: string | null;
  onContinue: () => void;
  onStart: () => void;
  onStartWith: (concept: { id: string; name: string }) => void;
  onGoal: () => void;
  /** `milestones`: the course and its concepts, for "Prepare for <exam>". */
  courseId?: string | null;
  nodes?: readonly GraphNode[];
  onStartGoal?: (topic: string, goal: LoopGoal) => void;
  /** `just_ask`: starts an ungraded chat. */
  onAsk?: () => void;
}) {
  const prep = usePrepare(onStartGoal ? courseId : null, nodes);
  const askOn = useFlag("just_ask") === "on" && !!onAsk;
  const intents = intentsFor({ prepare: prep, ask: askOn, continueTitle, startWith, courseName, dueCount, dueHref });
  // The board picks the exam first; without one, the whole-course session.
  const [picked, setPicked] = useState<IntentId | null>(null);
  const fallback = intents.find((i) => i.id === "prepare") ?? intents.find((i) => i.id === DEFAULT_INTENT)!;
  const current = intents.find((i) => i.id === picked) ?? fallback;
  const heading = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
    heading.current?.focus({ preventScroll: true });
  }, []);
  const name = useId();
  const start = () => {
    if (current.id === "prepare" && prep && onStartGoal) onStartGoal(prep.plan.topic, prep.plan.goal);
    else if (current.id === "ask" && onAsk) onAsk();
    else if (current.id === "continue") onContinue();
    else if (current.id === "concept" && startWith) onStartWith(startWith);
    else if (current.id === "goal") onGoal();
    else onStart();
  };
  const label = starting && current.startsNew ? LEARNING_COPY.starting : current.label;
  return (
    <div className={styles.root} data-testid="tutor-home">
      <div className={styles.col} data-testid="tutor-new-session-v2">
        <h2 ref={heading} tabIndex={-1} className={`h-serif ${styles.title}`}>{NEW_SESSION_COPY.title}</h2>
        <fieldset className={styles.intents} disabled={busy}>
          <legend className={styles.srOnly}>{NEW_SESSION_COPY.legend}</legend>
          {intents.map((i) => (
            <label key={i.id} className={styles.intent} data-testid={`tutor-new-intent-${i.id}`} data-picked={i.id === current.id ? "true" : "false"}>
              <input type="radio" name={name} value={i.id} checked={i.id === current.id} onChange={() => setPicked(i.id)} />
              <span className={styles.text}>
                <span className={styles.intentTitle}>{i.title}</span>
                <span className={styles.line}>{i.line}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <div className={styles.go}>
          {current.id === "review" && dueHref ? (
            <HandoffLink variant="primary" className={styles.start} testId="loop-start-guided" data-intent="review" href={dueHref}>
              {current.label}
            </HandoffLink>
          ) : (
            <button type="button" data-testid="loop-start-guided" data-intent={current.id} className={`btn btn--primary ${styles.start}`}
              onClick={start} disabled={busy}>
              {label}
            </button>
          )}
          {closesCurrent && current.startsNew && (
            <p className={styles.note} data-testid="tutor-new-wraps-up">{NEW_SESSION_COPY.wrapsUp(closesCurrent)}</p>
          )}
        </div>
      </div>
    </div>
  );
}
