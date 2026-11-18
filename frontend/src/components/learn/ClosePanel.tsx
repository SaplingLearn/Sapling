"use client";
import React, { useLayoutEffect, useRef } from "react";
import Link from "next/link";
import type { LoopCloseBaseline, LoopCloseConcept, LoopCloseResponse } from "@/lib/api";
import { retentionHref } from "@/context/RetentionDueContext";
import { CenteredCard } from "./CenteredCard";
import { modalOpen } from "./modalOpen";
import { WrapUpRating } from "./WrapUpRating";
import tutorStyles from "./tutor/tutor.module.css";

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

/** "What moved": each concept's change, or — with nothing measured — what
 *  happens next. The caption only explains a list that is there. */
function MovedCard({ concepts, names }: { concepts: LoopCloseConcept[]; names: Map<string, string> }) {
  const up = concepts.filter((c) => closeConceptView(c).dir === "up").length;
  return (
    <section className="card" aria-labelledby="loop-close-moved">
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

/**
 * Wireframe T10, the wrap-up (A60). Its links to Study (the reviews and the
 * retention check) show only while Study is visible: with `hide_study` on,
 * NavFeatureGate would send them to the dashboard. "How was that session?" is
 * asked here (`rating`), never after the student has left.
 */
export function ClosePanel({
  close, note, names, courseId, onNew, studyVisible, rating,
}: {
  /** Wireframe T10: back to the Tutor home to start the next session. */
  onNew?: () => void;
  close: LoopCloseResponse | null;
  /** Set when the stored close could not be read (the session was closed elsewhere). */
  note: string | null;
  names: Map<string, string>;
  courseId: string | null;
  /** False while the `hide_study` flag hides Study. */
  studyVisible: boolean;
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
        {studyVisible && (
          <Link data-testid="loop-close-study-link" href="/study" style={{ color: "var(--accent)" }}>
            Review what&apos;s due
          </Link>
        )}
      </CenteredCard>
    );
  }
  const rec = close.close;
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
          {studyVisible && courseId && <Link data-testid="loop-close-retention-link" href={retentionHref([courseId])} className="btn">
            Check retention after time away
          </Link>}
          {studyVisible && (
            <Link data-testid="loop-close-study-link" href="/study" className="btn">
              Review what&apos;s due
            </Link>
          )}
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
