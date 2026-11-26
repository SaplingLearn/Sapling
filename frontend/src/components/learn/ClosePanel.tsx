"use client";
import { CtaLink } from "@/components/ui/HandoffLink";
import { LEARNING_COPY } from "@/lib/learningCopy";
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { useMotionPresets } from "@/lib/motion";
import type { LoopCloseBaseline, LoopCloseConcept, LoopCloseResponse } from "@/lib/api";
import { useUser } from "@/context/UserContext";
import { useFlag } from "@/context/FlagsContext";
import {
  closeHandoffCtas,
  type HandoffVisibility,
} from "@/lib/learningHandoffs";
import { getStudyNext } from "@/lib/studyApi";
import { retentionHref } from "@/context/RetentionDueContext";
import { CenteredCard } from "./CenteredCard";
import { modalOpen } from "./modalOpen";
import { WrapUpRating } from "./WrapUpRating";
import tutorStyles from "./tutor/tutor.module.css";
import styles from "./ClosePanel.module.css";

/**
 * W3.3b: learner-next due ids for Practice what's due on wrap-up. Empty while
 * flags off / unread / failed — closeHandoffCtas then uses course+start.
 */
function usePracticeDueIds(courseId: string | null, enabled: boolean): readonly string[] {
  const { userId } = useUser();
  const loopOn = useFlag("learning_loop") === "on";
  const planOn = useFlag("quiz_concept_plan") === "on";
  const [ids, setIds] = useState<readonly string[]>([]);
  // Switched off (or nothing to read for): drop the last answer during render
  // rather than in the effect, so it never shows for a render.
  const active = enabled && !!courseId && !!userId && loopOn && planOn;
  if (!active && ids.length > 0) setIds([]);
  useEffect(() => {
    if (!enabled || !courseId || !userId || !loopOn || !planOn) return;
    let live = true;
    getStudyNext(userId, courseId)
      .then((r) => {
        if (live) setIds(r.due.map((c) => c.node_id));
      })
      .catch(() => {
        if (live) setIds([]);
      });
    return () => {
      live = false;
    };
  }, [enabled, courseId, userId, loopOn, planOn]);
  return ids;
}

/** Spec §13 A117: how one concept reads on the wrap-up. A concept first measured
 *  this session (`check_in` / `teaching`) starts at that measurement — it is a
 *  starting point, never a drop from the BKT prior — and only a move after it
 *  gets an arrow. A close stored before A117 has no `baseline`: its numbers are
 *  read as a change from the pre-session estimate, as they always were. */
export function closeConceptView(c: LoopCloseConcept): {
  baseline: LoopCloseBaseline;
  dir: "up" | "down" | "same";
  arrow: string;
  label: string;
} {
  const baseline = c.baseline ?? "pre_session";
  const dir = c.p_after > c.p_before ? "up" : c.p_after < c.p_before ? "down" : "same";
  if (baseline === "pre_session") {
    const label = dir === "up" ? "stronger" : dir === "down" ? "worth another look" : "about the same";
    return { baseline, dir, arrow: dir === "up" ? "↑" : dir === "down" ? "↓" : "→", label };
  }
  if (dir === "same") {
    const label = baseline === "check_in" ? "first measured at the check-in" : "first measured this session";
    return { baseline, dir, arrow: "•", label };
  }
  const since = baseline === "check_in" ? "the check-in" : "its first check";
  const label = dir === "up" ? `stronger since ${since}` : `lower since ${since} — worth another look`;
  return { baseline, dir, arrow: dir === "up" ? "↑" : "↓", label };
}

/** Prefer a concept that went down ("worth another look"), else the first. */
export function closeQuizConceptId(concepts: LoopCloseConcept[]): string | null {
  const down = concepts.find((c) => closeConceptView(c).dir === "down");
  return (down ?? concepts[0])?.node_id ?? null;
}

/** "What moved": each concept's change, or — with nothing measured — what
 *  happens next. The caption only explains a list that is there. */
function MovedCard({ concepts, names }: { concepts: LoopCloseConcept[]; names: Map<string, string> }) {
  const up = concepts.filter((c) => closeConceptView(c).dir === "up").length;
  return (
    <section className="card" aria-labelledby="loop-close-moved">
      <div className={tutorStyles.cardHead}>
        <div>
          <h3 id="loop-close-moved" className="h-serif">
            {concepts.length === 0 ? "Nothing measured yet" : `${up} of ${concepts.length} ${concepts.length === 1 ? "concept" : "concepts"} stronger`}
          </h3>
        </div>
      </div>
      <div className={tutorStyles.cardPad}>
        {concepts.length > 0 ? (
          <ul className={tutorStyles.moved}>
              {concepts.map((c) => {
                const view = closeConceptView(c);
                return (
                  <li
                    key={c.node_id}
                    data-testid={`loop-close-concept-${c.node_id}`}
                    data-baseline={view.baseline}
                    data-direction={view.dir}
                    className={tutorStyles.movedRow}
                  >
                    <span>
                      <span aria-hidden data-dir={view.dir} className={styles.arrow}>{view.arrow}</span>
                      {names.get(c.node_id) ?? "A concept"}
                    </span>
                    <span data-dir={view.dir} className={styles.movedLabel}>{view.label}</span>
                  </li>
                );
              })}
          </ul>
        ) : (
          <p className={styles.quiet}>Your tutor picks up from here next session.</p>
        )}
      </div>
    </section>
  );
}

function CloseHandoffLinks({
  courseId,
  quizConceptId,
  visibility,
}: {
  courseId: string | null;
  quizConceptId?: string | null;
  visibility: HandoffVisibility;
}) {
  const dueConceptIds = usePracticeDueIds(
    courseId,
    visibility.study && visibility.quiz,
  );
  const links = closeHandoffCtas({ courseId, quizConceptId, dueConceptIds, visibility });
  if (links.length === 0) return null;
  return (
    <>
      {links.map((link) => (
        <CtaLink key={link.testId} cta={link} className={styles.press} />
      ))}
    </>
  );
}

/**
 * Wireframe T10, the wrap-up (A60). Cross-links to Study / Quiz / Tree use the
 * W3.4 handoff copy and hide when the matching `hide_*` flag is on
 * (NavFeatureGate would only send them to the dashboard). "How was that
 * session?" is asked here (`rating`), never after the student has left.
 */
export function ClosePanel({
  close, note, names, courseId, onNew, visibility, rating,
}: {
  /** Wireframe T10: back to the Tutor home to start the next session. */
  onNew?: () => void;
  close: LoopCloseResponse | null;
  /** Set when the stored close could not be read (the session was closed elsewhere). */
  note: string | null;
  names: Map<string, string>;
  courseId: string | null;
  /** hide_study / hide_quiz / hide_tree (and tutor unused here). */
  visibility: HandoffVisibility;
  /** The session the wrap-up asks to rate (`claimWrapUpAsk`), else null. */
  rating: { sessionId: string; topic?: string } | null;
}) {
  // spec §13 A135: the wrap-up replaces the lesson (and the End session button
  // that asked for it), so once it is there its heading — or the note that the
  // session was closed elsewhere — takes focus and is read out.
  const focusTarget = useRef<HTMLElement | null>(null);
  const setFocusTarget = (el: HTMLElement | null) => {
    focusTarget.current = el;
  };
  const ready = close !== null || note !== null;
  useLayoutEffect(() => {
    if (ready && !modalOpen()) focusTarget.current?.focus();
  }, [ready]);
  const m = useMotionPresets();
  if (!close) {
    if (!note) return <div className={styles.wrapping}>Wrapping up…</div>;
    return (
      <CenteredCard testId="loop-close-done">
        <p ref={setFocusTarget} tabIndex={-1} className={styles.note}>{note}</p>
        <div className={styles.links}>
          <CloseHandoffLinks courseId={courseId} visibility={visibility} />
        </div>
      </CenteredCard>
    );
  }
  const rec = close.close;
  const quizConceptId = closeQuizConceptId(rec.concepts);
  const item = m.list.item;
  return (
    <div className={styles.root}>
      {/* The wrap-up replaces the lesson: its sections arrive one after another. */}
      <motion.div className={tutorStyles.col} variants={m.list.container} initial="hidden" animate="shown">
        <motion.h2 variants={item} ref={setFocusTarget} tabIndex={-1} className={`h-serif ${styles.title}`}>Session wrap-up</motion.h2>
        <motion.div variants={item} className={tutorStyles.closeGrid}>
          <MovedCard concepts={rec.concepts} names={names} />
          <section className="card" aria-labelledby="loop-close-summary-h">
            <div className={tutorStyles.cardHead}>
              <div>
                <h3 id="loop-close-summary-h" className="h-serif">What you covered</h3>
              </div>
            </div>
            <div className={tutorStyles.cardPad}>
              <p data-testid="loop-close-summary" className={styles.summary}>
                {rec.summary}
              </p>
            </div>
          </section>
        </motion.div>
        {/* The Tutor redesign cut A60's self-evaluation prompt and W3.5a's
            concept mini-map here: neither saved anything nor changed a next step. */}
        {rec.if_then && (
          <motion.section variants={item} data-testid="loop-close-if-then" className={`card ${tutorStyles.cardPad} ${styles.tight} ${styles.plan}`}>
            <h3 className={`h-serif ${styles.planTitle}`}>Next time</h3>
            <div className={styles.planText}>{rec.if_then}</div>
          </motion.section>
        )}
        {rating && <WrapUpRating key={rating.sessionId} sessionId={rating.sessionId} topic={rating.topic} />}
        <motion.div variants={item} data-testid="loop-close-done" className={styles.done}>
          {visibility.study && courseId && <Link data-testid="loop-close-retention-link" href={retentionHref([courseId])} className={`btn ${styles.press}`}>
            Check retention after time away
          </Link>}
          <CloseHandoffLinks
            courseId={courseId}
            quizConceptId={quizConceptId}
            visibility={visibility}
          />
          {onNew && (
            <button type="button" data-testid="loop-close-new-session" className={`btn btn--primary ${styles.press}`} onClick={onNew}>
              {LEARNING_COPY.newSession}
            </button>
          )}
        </motion.div>
      </motion.div>
    </div>
  );
}
