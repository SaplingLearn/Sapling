"use client";

import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useRetentionDue } from "@/context/RetentionDueContext";
import {
  answerRetentionCheck, markRetentionShown, startRetentionCheck, type EnrolledCourse, type RetentionItem,
} from "@/lib/api";
import { extractErrorDetail, humanizeError } from "@/lib/errorMessage";
import { useFeedbackHold } from "@/lib/feedbackPacing";
import styles from "./LoopLearn.module.css";
import { useCrisisSupport } from "../safety/CrisisSupportCard";
import { LOOP_ANSWER_MAX } from "@/lib/inputLimits";

/** Spec §13 A126: how often and how long the page was hidden while one item
 *  was on screen. Telemetry for the outcome record — the server clamps it and
 *  never grades with it. */
interface Visibility { count: number; hiddenMs: number; hiddenSince: number | null }

function visibilityNow(): Visibility {
  const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
  return { count: hidden ? 1 : 0, hiddenMs: 0, hiddenSince: hidden ? Date.now() : null };
}

function hiddenReport(v: Visibility): { hidden_count: number; hidden_s: number } {
  const ongoing = v.hiddenSince !== null ? Date.now() - v.hiddenSince : 0;
  return { hidden_count: v.count, hidden_s: (v.hiddenMs + ongoing) / 1000 };
}

/** Opening a post-test commits its pose. Only an explicit learner action may
 * call it; eligibility and delayed/assisted credit remain entirely server-owned.
 *
 * `initialCourseId` is the deep link's course (`?retention-course=`). A link to
 * a course that is not in `courses` falls back to the first course and SAYS so,
 * until the student picks one: a silent switch would check the wrong course.
 *
 * Keyboard and screen reader (spec §13 A135, as DueQueue does it): an action
 * whose control goes away moves focus to what it produced — Open to the first
 * question's answer (or the line saying none is open), Check answer and "I don't
 * know" to the result, Continue to the next question's answer (or the line
 * saying the set is finished), a failure to its error. Every result and status
 * line is written into a live region that is already on the page. */
export function RetentionCheck({ userId, courses, initialCourseId = "" }: {
  userId: string; courses: EnrolledCourse[]; initialCourseId?: string;
}) {
  const [selected, setSelected] = useState(initialCourseId);
  const noteId = useId();
  const courseId = courses.some((course) => course.course_id === selected)
    ? selected : courses[0]?.course_id ?? "";
  // The link's course is not one of the student's: say which course shows instead.
  const fellBack = !!initialCourseId && selected === initialCourseId && !!courseId && courseId !== selected;
  const shown = courses.find((course) => course.course_id === courseId);
  return (
    <section aria-label="Retention check" className={`card ${styles.retention}`} style={{ margin: 0 }}>
      <h2 style={{ margin: 0, fontSize: 17 }}>Retention check</h2>
      <p style={{ margin: 0, fontSize: 13 }}>Check what you remember after time away. No tutor hints are offered here; the server tracks any help or intervening practice.</p>
      <label>Course
        <select aria-label="Retention course" aria-describedby={fellBack ? noteId : undefined} data-testid="retention-course" value={courseId} onChange={(event) => setSelected(event.target.value)} style={{ display: "block", width: "100%", minWidth: 0, marginTop: 4 }}>
          {!courseId && <option value="">Add a course first</option>}
          {courses.map((course) => <option key={course.course_id} value={course.course_id}>{course.course_name}</option>)}
        </select>
      </label>
      {fellBack && (
        <p id={noteId} data-testid="retention-course-fallback" style={{ margin: 0, fontSize: 13 }}>
          The course in your link isn&apos;t one of your courses, so this check is set to {shown?.course_name ?? "your first course"}. Pick another course above if you meant a different one.
        </p>
      )}
      <RetentionSession key={`${userId}:${courseId}`} userId={userId} courseId={courseId} />
    </section>
  );
}

/** Where focus goes once the action in flight settles (see RetentionCheck). */
type FocusTarget = "item" | "result";

const STATUS_LINE: React.CSSProperties = { margin: "10px 0 0", fontSize: 13 };

function RetentionSession({ userId, courseId }: { userId: string; courseId: string }) {
  // docs/safety/crisis-support.md: an answer the crisis screen answered
  const crisis = useCrisisSupport();
  const [items, setItems] = useState<RetentionItem[] | null>(null);
  const [index, setIndex] = useState(0);
  const [answer, setAnswer] = useState("");
  const [choice, setChoice] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<boolean | null>(null);
  // The last item could not be answered any more (a 404): it was skipped.
  const [skipped, setSkipped] = useState(false);
  const mounted = useRef(true);
  const focusNext = useRef<FocusTarget | null>(null);
  const itemRef = useRef<HTMLDivElement>(null);
  const resultRef = useRef<HTMLParagraphElement>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);
  const request = useRef(0);
  const visibility = useRef<Visibility>({ count: 0, hiddenMs: 0, hiddenSince: null });
  const { refresh: refreshDue } = useRetentionDue();
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const resetDraft = () => { setAnswer(""); setChoice(""); setReason(""); setResult(null); };
  // spec §13 A135: apply `focusNext` once nothing is in flight and its target
  // is on screen. A failure focuses its error; a dialog (the crisis card) keeps focus.
  useLayoutEffect(() => {
    const want = focusNext.current;
    if (!want || busy) return;
    if (document.querySelector('[aria-modal="true"]')) { focusNext.current = null; return; }
    const target = errorRef.current ?? (want === "result" ? resultRef.current
      : itemRef.current?.querySelector<HTMLElement>("textarea, input") ?? statusRef.current);
    if (!target) return;
    focusNext.current = null;
    target.focus();
  });
  /** Move to the next question (Continue, or a skip). */
  const advance = () => { focusNext.current = "item"; setIndex((current) => current + 1); resetDraft(); };
  const open = async () => {
    if (!courseId || !userId || busy) return;
    const mine = ++request.current;
    focusNext.current = "item";
    setBusy(true); setError(null); setSkipped(false);
    try {
      const response = await startRetentionCheck(userId, courseId);
      if (!mounted.current || mine !== request.current) return;
      setItems(response.items); setIndex(0); resetDraft();
      refreshDue(); // opening changed what is due (A126)
    } catch (err) {
      if (mounted.current && mine === request.current) setError(humanizeError(err, "Couldn't open retention checks. Try again."));
    } finally {
      if (mounted.current && mine === request.current) setBusy(false);
    }
  };
  const item = items?.[index];
  // No feedback survey during an opened retention check (lib/feedbackPacing.ts).
  useFeedbackHold(!!item);
  // A126: the item is on screen — the server stamps its first display (the
  // answer's latency runs from it), and the page's hidden periods are counted
  // from now until the answer. A failed stamp only leaves the latency unknown.
  const nodeId = item?.node_id;
  const questionHash = item?.question_hash;
  useEffect(() => {
    if (!nodeId || !questionHash) return;
    visibility.current = visibilityNow();
    // The server keeps the FIRST display (a conditional UPDATE on served_at IS NULL).
    void (async () => {
      try { await markRetentionShown({ user_id: userId, node_id: nodeId, question_hash: questionHash }); } catch { /* telemetry only */ }
    })();
    const onVisibility = () => {
      const v = visibility.current;
      if (document.visibilityState === "hidden") {
        if (v.hiddenSince === null) { v.count += 1; v.hiddenSince = Date.now(); }
      } else if (v.hiddenSince !== null) {
        v.hiddenMs += Date.now() - v.hiddenSince;
        v.hiddenSince = null;
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [nodeId, questionHash, userId]);
  const submit = async (idk: boolean) => {
    if (!item || busy || result !== null) return;
    const mine = request.current;
    focusNext.current = "result";
    setBusy(true); setError(null); setSkipped(false);
    try {
      const response = await answerRetentionCheck({ user_id: userId, node_id: item.node_id, question_hash: item.question_hash, idk,
        ...(idk ? {} : item.format === "mc_reason" ? { selected_option: choice, reason } : { answer }),
        ...hiddenReport(visibility.current) });
      if (!mounted.current || mine !== request.current) return;
      if (crisis.intercept(response)) { setAnswer(""); setReason(""); return; } // nothing graded; still open
      if ("correct" in response) { setResult(response.correct); refreshDue(); }
      else setError("Answer in your own words. Nothing was recorded; you can try again.");
    } catch (err) {
      if (!mounted.current || mine !== request.current) return;
      const { status } = extractErrorDetail(err);
      if (status === 404) {
        // withdrawn since the set opened: every resend would 404 too — move on
        advance(); setSkipped(true); refreshDue();
      } else if (status === 409) {
        setItems(null);
        setError("This question is no longer open. Open eligible checks again to continue.");
      } else setError(humanizeError(err, "Couldn't check your answer. Your work is still here; try again."));
    } finally {
      if (mounted.current && mine === request.current) setBusy(false);
    }
  };
  const canSubmit = !!item && !busy && (item.format === "mc_reason" ? !!choice && !!reason.trim() : !!answer.trim());
  return <>
    {crisis.dialog}
    {/* A block, not a flex item: the button keeps its own width (the card's
        column stretched it into something that read as a text field), and the
        live region below it takes no gap while it is empty. */}
    <div>
      <button type="button" data-testid="retention-open" className={item ? "btn btn--sm" : "btn btn--sm btn--primary"} disabled={!courseId || busy} onClick={() => void open()}>{busy ? "Checking…" : "Open eligible retention checks"}</button>
      {/* Always in the DOM, so each status line is announced when it appears. */}
      <div aria-live="polite">
        {skipped && <p data-testid="retention-skipped" style={STATUS_LINE}>That question is no longer available, so it was skipped.</p>}
        {items?.length === 0 && <p ref={statusRef} tabIndex={-1} data-testid="retention-empty" style={STATUS_LINE}>No eligible unseen retention checks are available for this course. Checks open at fixed times after you first study a concept; you may need more time or new check material.</p>}
        {items && items.length > 0 && !item && <p ref={statusRef} tabIndex={-1} data-testid="retention-finished" style={STATUS_LINE}>This set is finished. A few answers do not establish mastery; keep checking what you retain over time.</p>}
      </div>
    </div>
    {error && <p ref={errorRef} tabIndex={-1} role="alert" style={{ margin: 0, fontSize: 13 }}>{error}</p>}
    {item && <div ref={itemRef} data-testid="retention-item" style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
      <p style={{ margin: 0, fontSize: 12 }}>Question {index + 1} of {items?.length}</p>
      <div>
        <p style={{ margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.prompt}</p>
        {/* Present while the question is, so the result is announced when it is written. */}
        <div aria-live="polite">
          {result !== null && <p ref={resultRef} tabIndex={-1} data-testid="retention-result" style={{ margin: "8px 0 0" }}>{result ? "Correct on this retention check. One answer is not proof of mastery." : "Not correct on this check. Review your material before trying again."}</p>}
        </div>
      </div>
      {result === null ? <form aria-label="Retention answer" onSubmit={(event) => { event.preventDefault(); if (canSubmit) void submit(false); }} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {item.format === "mc_reason" ? <>
          <fieldset disabled={busy} style={{ minWidth: 0, margin: 0 }}><legend>Your answer</legend>
            {(item.options ?? []).map((option) => <label key={option.letter} className={styles.scopeOption}>
              <input type="radio" name="retention-option" checked={choice === option.letter} onChange={() => setChoice(option.letter)} />
              <span>{option.letter}. {option.text}</span>
            </label>)}
          </fieldset>
          <label>Your reasoning<input data-testid="retention-reason" maxLength={LOOP_ANSWER_MAX} value={reason} disabled={busy} onChange={(event) => setReason(event.target.value)} className={styles.scopeText} /></label>
        </> : <label>Your answer<textarea data-testid="retention-answer" maxLength={LOOP_ANSWER_MAX} rows={3} value={answer} disabled={busy} onChange={(event) => setAnswer(event.target.value)} className={styles.scopeText} /></label>}
        <div className={styles.scopeActions}>
          <button data-testid="retention-submit" type="submit" className="btn btn--sm btn--primary" disabled={!canSubmit}>Check answer</button>
          <button data-testid="retention-idk" type="button" className="btn btn--sm" disabled={busy} onClick={() => void submit(true)}>I don&apos;t know</button>
        </div>
      </form> : <button data-testid="retention-next" type="button" className="btn btn--sm" style={{ alignSelf: "flex-start" }} onClick={() => { setSkipped(false); advance(); }}>Continue</button>}
    </div>}
  </>;
}
