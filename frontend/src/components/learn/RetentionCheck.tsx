"use client";

import React, { useEffect, useRef, useState } from "react";
import { useRetentionDue } from "@/context/RetentionDueContext";
import {
  answerRetentionCheck, markRetentionShown, startRetentionCheck, type EnrolledCourse, type RetentionItem,
} from "@/lib/api";
import { extractErrorDetail, humanizeError } from "@/lib/errorMessage";
import { useFeedbackHold } from "@/lib/feedbackPacing";
import styles from "./LoopLearn.module.css";
import { useCrisisSupport } from "../safety/CrisisSupportCard";

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
 * call it; eligibility and delayed/assisted credit remain entirely server-owned. */
export function RetentionCheck({ userId, courses, initialCourseId = "" }: {
  userId: string; courses: EnrolledCourse[]; initialCourseId?: string;
}) {
  const [selected, setSelected] = useState(initialCourseId);
  const courseId = courses.some((course) => course.course_id === selected)
    ? selected : courses[0]?.course_id ?? "";
  return (
    <section aria-label="Retention check" className={`card ${styles.retention}`}>
      <h2 style={{ margin: 0, fontSize: 17 }}>Retention check</h2>
      <p style={{ margin: 0, fontSize: 13 }}>Check what you remember after time away. No tutor hints are offered here; the server tracks any help or intervening practice.</p>
      <label>Course
        <select aria-label="Retention course" data-testid="retention-course" value={courseId} onChange={(event) => setSelected(event.target.value)} style={{ display: "block", width: "100%", minWidth: 0, marginTop: 4 }}>
          {!courseId && <option value="">Add a course first</option>}
          {courses.map((course) => <option key={course.course_id} value={course.course_id}>{course.course_name}</option>)}
        </select>
      </label>
      <RetentionSession key={`${userId}:${courseId}`} userId={userId} courseId={courseId} />
    </section>
  );
}

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
  const mounted = useRef(true);
  const request = useRef(0);
  const visibility = useRef<Visibility>({ count: 0, hiddenMs: 0, hiddenSince: null });
  const { refresh: refreshDue } = useRetentionDue();
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const resetDraft = () => { setAnswer(""); setChoice(""); setReason(""); setResult(null); };
  const open = async () => {
    if (!courseId || !userId || busy) return;
    const mine = ++request.current;
    setBusy(true); setError(null);
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
    setBusy(true); setError(null);
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
      if (extractErrorDetail(err).status === 409) {
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
    <button type="button" data-testid="retention-open" className="btn btn--sm" disabled={!courseId || busy} onClick={() => void open()}>{busy ? "Checking…" : "Open eligible retention checks"}</button>
    {error && <p role="alert" style={{ margin: 0, fontSize: 13 }}>{error}</p>}
    {items?.length === 0 && <p data-testid="retention-empty" role="status">No eligible unseen retention checks are available for this course. Checks open at fixed times after you first study a concept; you may need more time or new check material.</p>}
    {items && items.length > 0 && !item && <p data-testid="retention-finished" role="status">This set is finished. A few answers do not establish mastery; keep checking what you retain over time.</p>}
    {item && <div data-testid="retention-item" style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
      <p style={{ margin: 0, fontSize: 12 }}>Question {index + 1} of {items?.length}</p>
      <p style={{ margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.prompt}</p>
      {result === null ? <form aria-label="Retention answer" onSubmit={(event) => { event.preventDefault(); if (canSubmit) void submit(false); }} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {item.format === "mc_reason" ? <>
          <fieldset disabled={busy} style={{ minWidth: 0, margin: 0 }}><legend>Your answer</legend>
            {(item.options ?? []).map((option) => <label key={option.letter} className={styles.scopeOption}>
              <input type="radio" name="retention-option" checked={choice === option.letter} onChange={() => setChoice(option.letter)} />
              <span>{option.letter}. {option.text}</span>
            </label>)}
          </fieldset>
          <label>Your reasoning<input data-testid="retention-reason" value={reason} disabled={busy} onChange={(event) => setReason(event.target.value)} className={styles.scopeText} /></label>
        </> : <label>Your answer<textarea data-testid="retention-answer" rows={3} value={answer} disabled={busy} onChange={(event) => setAnswer(event.target.value)} className={styles.scopeText} /></label>}
        <div className={styles.scopeActions}>
          <button data-testid="retention-submit" type="submit" className="btn btn--sm btn--primary" disabled={!canSubmit}>Check answer</button>
          <button data-testid="retention-idk" type="button" className="btn btn--sm" disabled={busy} onClick={() => void submit(true)}>I don&apos;t know</button>
        </div>
      </form> : <>
        <p data-testid="retention-result" role="status">{result ? "Correct on this retention check. One answer is not proof of mastery." : "Not correct on this check. Review your material before trying again."}</p>
        <button data-testid="retention-next" type="button" className="btn btn--sm" onClick={() => { setIndex((current) => current + 1); resetDraft(); }}>Continue</button>
      </>}
    </div>}
  </>;
}
