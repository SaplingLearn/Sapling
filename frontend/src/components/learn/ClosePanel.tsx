"use client";
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
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
import { LearnerMiniMapStub } from "./LearnerMiniMapStub";
import { modalOpen } from "./modalOpen";
import { WrapUpRating } from "./WrapUpRating";
import tutorStyles from "./tutor/tutor.module.css";

/**
 * W3.3b: learner-next due ids for Practice what's due on wrap-up. Empty while
 * flags off / unread / failed — closeHandoffCtas then uses course+start.
 */
function usePracticeDueIds(courseId: string | null, enabled: boolean): readonly string[] {
  const { userId } = useUser();
  const loopOn = useFlag("learning_loop") === "on";
  const planOn = useFlag("quiz_concept_plan") === "on";
  const [ids, setIds] = useState<readonly string[]>([]);
  useEffect(() => {
    if (!enabled || !courseId || !userId || !loopOn || !planOn) {
      setIds([]);
      return;
    }
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
    <section className="card fade-in" aria-labelledby="loop-close-moved">
      <div className={tutorStyles.cardHead}>
        <div>
          <span className="label-micro">What moved</span>
          <h3 id="loop-close-moved" className="h-serif">
            {concepts.length === 0 ? "Nothing measured yet" : `${up} of ${concepts.length} ${concepts.length === 1 ? "concept" : "concepts"} stronger`}
          </h3>
        </div>
      </div>
      <div className={tutorStyles.cardPad}>
        {concepts.length > 0 ? (
          <>
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
                      <span aria-hidden style={{ color: view.dir === "up" ? "var(--sap-600)" : view.dir === "down" ? "var(--warn)" : "var(--text-muted)", marginRight: 6 }}>{view.arrow}</span>
                      {names.get(c.node_id) ?? "A concept"}
                    </span>
                    <span style={{ color: view.dir === "down" ? "var(--warn)" : "var(--text-muted)", fontSize: 13 }}>{view.label}</span>
                  </li>
                );
              })}
            </ul>
            <p data-testid="loop-close-moved-caption" style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>Change from where you started this session.</p>
          </>
        ) : (
          <p style={{ margin: 0, fontSize: 13, color: "var(--text-muted)" }}>Your tutor picks up from here next session.</p>
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
        <Link
          key={link.testId}
          data-testid={link.testId}
          href={link.href}
          className="btn"
        >
          {link.label}
        </Link>
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
  if (!close) {
    if (!note) return <div style={{ padding: 40, color: "var(--text-dim)" }}>Wrapping up…</div>;
    return (
      <CenteredCard testId="loop-close-done">
        <p ref={setFocusTarget} tabIndex={-1} style={{ margin: "0 0 12px", fontSize: 14, color: "var(--text-dim)" }}>{note}</p>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <CloseHandoffLinks courseId={courseId} visibility={visibility} />
        </div>
      </CenteredCard>
    );
  }
  const rec = close.close;
  const quizConceptId = closeQuizConceptId(rec.concepts);
  return (
    <div style={{ flex: 1, overflowY: "auto" }}>
      <div className={tutorStyles.col}>
        <h2 ref={setFocusTarget} tabIndex={-1} className="h-serif" style={{ margin: 0, fontSize: 24 }}>Session wrap-up</h2>
        <div className={tutorStyles.closeGrid}>
          <MovedCard concepts={rec.concepts} names={names} />
          <section className="card" aria-labelledby="loop-close-summary-h">
            <div className={tutorStyles.cardHead}>
              <div>
                <span className="label-micro">Summary</span>
                <h3 id="loop-close-summary-h" className="h-serif">What you covered</h3>
              </div>
            </div>
            <div className={tutorStyles.cardPad}>
              <p data-testid="loop-close-summary" style={{ margin: 0, font: "400 14px/1.6 var(--font-serif)", whiteSpace: "pre-wrap" }}>
                {rec.summary}
              </p>
            </div>
          </section>
        </div>
        {/* A60: the self-evaluation is a reflection prompt only — nothing is saved. */}
        <section data-testid="loop-close-self-eval" className={`card ${tutorStyles.cardPad}`} style={{ gap: 6 }}>
          <span className="label-micro">Reflect</span>
          <div style={{ fontSize: 15, fontStyle: "italic", fontFamily: "var(--font-serif)" }}>{rec.self_eval}</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Take a moment with it — it&apos;s just for you, nothing is saved.
          </div>
        </section>
        {/* W3.5a: generative mini-map — client edges only; never mastery / graph_edges. */}
        {rec.concepts.length >= 2 && (
          <LearnerMiniMapStub
            concepts={rec.concepts.map((c) => ({
              id: c.node_id,
              label: names.get(c.node_id) ?? "A concept",
            }))}
          />
        )}
        {rec.if_then && (
          <section data-testid="loop-close-if-then" className={`card ${tutorStyles.cardPad}`} style={{ gap: 6, background: "var(--accent-soft)", borderColor: "var(--accent-border)" }}>
            <span className="label-micro">Your plan for next time</span>
            <div style={{ fontSize: 15 }}>{rec.if_then}</div>
          </section>
        )}
        {rating && <WrapUpRating key={rating.sessionId} sessionId={rating.sessionId} topic={rating.topic} />}
        <div
          data-testid="loop-close-done"
          style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", fontSize: 14, color: "var(--text-dim)" }}
        >
          <span style={{ flex: 1, minWidth: 120 }}>Session closed.</span>
          {visibility.study && courseId && <Link data-testid="loop-close-retention-link" href={retentionHref([courseId])} className="btn">
            Check retention after time away
          </Link>}
          <CloseHandoffLinks
            courseId={courseId}
            quizConceptId={quizConceptId}
            visibility={visibility}
          />
          {onNew && (
            <button type="button" data-testid="loop-close-new-session" className="btn btn--primary" onClick={onNew}>
              Start a new session
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
