"use client";

import React, { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useMotionPresets } from "@/lib/motion";
import type { LoopDiagnosis, LoopGoal, LoopGoalProgress } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import styles from "./LoopLearn.module.css";
import own from "./LearningScope.module.css";
import { LOOP_GOAL_MAX_TARGETS, LOOP_GOAL_TEXT_MAX } from "./loopShared";

/** The session's goal under the stepper. The whole-course default says
 *  nothing (the redesign's "say each fact once": no goal is the normal case),
 *  and neither does the load; only a goal or a failed read is shown. */
export function ScopeSummary({ error, ready, goal, names, onRetry }: {
  error: boolean;
  ready: boolean;
  goal: LoopGoal | null;
  names: Map<string, string>;
  onRetry: () => void;
}) {
  if (!error && (!ready || !goal)) return null;
  return (
    <div className={styles.scopeSummary} data-testid="loop-goal-summary">
      {error ? <><span>Couldn&apos;t load your goal. </span>
        <button type="button" data-testid="loop-goal-retry" className={`btn btn--sm ${own.press}`} onClick={onRetry}>Try again</button></>
        : goal && <><strong>Goal: </strong>{goal.text || goal.target_node_ids.map((id) => names.get(id) ?? "Selected concept").join(", ")}</>}
    </div>
  );
}

/** Where a goal session stands once its planned practice is done. */
export function GoalProgressNote({ progress, names }: { progress: LoopGoalProgress; names: Map<string, string> }) {
  return (
    <div data-testid="loop-goal-progress" role="status" className={styles.scopeSummary}>
      {progress.status === "continue_available"
        ? "The next step toward your goal is ready to review. Approve the new plan before continuing."
        : progress.status === "needs_more_practice"
          ? "Your goal still needs prerequisite practice. Review source material; more practice is needed before the goal can continue."
          : "You finished the practice planned for this session. This does not establish mastery; check what you retain after time away."}
      {progress.unresolved_prerequisite_ids.length > 0 && <span> Prerequisites needing practice: {progress.unresolved_prerequisite_ids.map((id) => names.get(id) ?? "A prerequisite").join(", ")}.</span>}
      {progress.remaining_target_node_ids.length > 0 && <span> Goal concepts remaining: {progress.remaining_target_node_ids.map((id) => names.get(id) ?? "A selected concept").join(", ")}.</span>}
    </div>
  );
}

export function GoalEditor({ goal, nodes, busy, error, onSave, onCancel, loadingNodes = false, nodesError = false, onRetryNodes }: {
  goal: LoopGoal | null;
  nodes: GraphNode[];
  busy: boolean;
  error: string | null;
  onSave: (goal: LoopGoal | null) => void;
  onCancel: () => void;
  loadingNodes?: boolean;
  nodesError?: boolean;
  onRetryNodes?: () => void;
}) {
  const [text, setText] = useState(goal?.text ?? "");
  const [targets, setTargets] = useState(goal?.target_node_ids ?? []);
  const [wholeCourse, setWholeCourse] = useState(false);
  const firstField = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { firstField.current?.focus(); }, []);
  const m = useMotionPresets();
  const available = new Set(nodes.map((n) => n.id));
  const confirmed = targets.filter((id) => available.has(id));
  const canSave = !busy && (wholeCourse || (!loadingNodes && !nodesError && confirmed.length > 0 && confirmed.length <= LOOP_GOAL_MAX_TARGETS));
  return (
    <div className={styles.scopeEditor}>
      <form className={`card ${styles.scopeCard}`} aria-label="Learning goal" onSubmit={(event) => {
        event.preventDefault();
        if (canSave) onSave(wholeCourse ? null : { text: text.trim(), target_node_ids: confirmed });
      }}>
        <h2 className={`h-serif ${own.title}`}>What do you want to learn?</h2>
        <p className={own.lede}>
          Say what you want to learn, then pick the concepts it covers. The tutor checks those and what they build on.
        </p>
        <label htmlFor="loop-goal-text">Your goal in your own words</label>
        <textarea ref={firstField} id="loop-goal-text" data-testid="loop-goal-text" value={text} maxLength={LOOP_GOAL_TEXT_MAX} rows={3}
          disabled={busy || wholeCourse} className={styles.scopeText} onChange={(event) => setText(event.target.value)}
          placeholder="For example: explain how negative numbers are represented" />
        <fieldset disabled={busy} className={styles.scopeFieldset}>
          <legend>What to cover</legend>
          <label className={styles.scopeOption}>
            <input type="radio" data-testid="loop-goal-whole-course" name="loop-goal-scope" checked={wholeCourse} onChange={() => setWholeCourse(true)} />
            <span>Explore the whole course</span>
          </label>
          <label className={styles.scopeOption}>
            <input type="radio" data-testid="loop-goal-selected-concepts" name="loop-goal-scope" checked={!wholeCourse} onChange={() => setWholeCourse(false)} />
            <span>Focus on selected concepts</span>
          </label>
        </fieldset>
        {/* Switching scope opens or closes the concept list in place. */}
        <AnimatePresence initial={false}>
        {!wholeCourse && (
          <motion.div key="targets" {...m.collapse}>
          <fieldset disabled={busy} className={styles.scopeFieldset}>
            <legend>Pick concepts</legend>
            <p className={own.hint}>
              Only this course&apos;s concepts are listed. Your words above don&apos;t pick any.
            </p>
            {loadingNodes && <p role="status">Loading course concepts…</p>}
            {nodesError && <div role="alert"><p>Couldn&apos;t load this course&apos;s concepts.</p>
              <button type="button" data-testid="loop-goal-retry-concepts" className={`btn btn--sm ${own.press}`} disabled={busy} onClick={onRetryNodes}>Retry course concepts</button></div>}
            <div className={styles.scopeOptions}>
              {nodes.map((node) => (
                <label key={node.id} className={styles.scopeOption}>
                  <input type="checkbox" checked={confirmed.includes(node.id)} data-testid={`loop-goal-target-${node.id}`}
                    disabled={!confirmed.includes(node.id) && confirmed.length >= LOOP_GOAL_MAX_TARGETS}
                    onChange={(event) => setTargets((current) => event.target.checked
                      ? [...current, node.id] : current.filter((id) => id !== node.id))} />
                  <span>{node.name}</span>
                </label>
              ))}
            </div>
            {nodes.length === 0 && !loadingNodes && !nodesError && <p role="status">No target concepts are available for this course yet. You can explore the whole course or add material in Library.</p>}
            <p role="status" className={own.count}>{confirmed.length} of {LOOP_GOAL_MAX_TARGETS} selected</p>
          </fieldset>
          </motion.div>
        )}
        </AnimatePresence>
        {error && <p role="alert" className={own.error}>{error}</p>}
        <div className={styles.scopeActions}>
          <button type="submit" className={`btn btn--primary ${own.press}`} disabled={!canSave} data-testid="loop-goal-save">{busy ? "Saving…" : "Save goal"}</button>
          <button type="button" data-testid="loop-goal-cancel" className={`btn btn--ghost ${own.press}`} disabled={busy} onClick={onCancel}>Cancel</button>
        </div>
        <p className={own.footnote}>
          Your earlier answers still count. You may get a short check-in before you start.
        </p>
      </form>
    </div>
  );
}

// Plain words for the check-in's result (the redesign's banned-terms rule: no
// "bounded", "independent", "observations" or "assessed" in student copy).
const STOP_COPY: Record<string, string> = {
  session_cap: "The check-in reached its question limit.",
  per_skill_cap: "Some concepts reached their question limit.",
  session_limit: "The check-in reached its question limit.",
  skill_limit: "Some concepts reached their question limit.",
  coverage_limit: "The check-in couldn't cover every concept.",
  item_bank_exhausted: "Some concepts ran out of questions.",
  no_items: "Some concepts don't have questions yet.",
  no_check_items: "Some concepts don't have questions yet.",
  novice_floor: "We'll start with the basics.",
};

const STATUS_COPY: Record<string, string> = {
  bracketed: "Here's where you're starting. It's a first estimate and it changes as you practise.",
  limited: "The check-in covered some concepts. The rest start from the beginning.",
  in_progress: "The check-in is still going.",
  not_assessed: "The check-in hasn't covered these concepts yet.",
};
const SKILL_COPY: Record<string, string> = {
  bracketed: "found your starting level",
  partial: "still finding your level",
  above_range: "right even on the hardest questions",
  below_range: "starting with the basics",
  inconsistent: "mixed results so far",
  untested: "not checked yet",
};

export function DiagnosisSummary({ diagnosis, names }: { diagnosis: LoopDiagnosis | null; names: Map<string, string> }) {
  if (!diagnosis) return null;
  return (
    <section aria-label="What the check-in showed" data-testid="loop-diagnosis" className={styles.diagnosis}>
      <h3 className={own.diagnosisTitle}>What the check-in showed</h3>
      <p className={own.status}>{STATUS_COPY[diagnosis.status] ?? "The check-in is incomplete."}</p>
      {diagnosis.stop_reason && STOP_COPY[diagnosis.stop_reason] && <p className={own.stop}>{STOP_COPY[diagnosis.stop_reason]}</p>}
      {diagnosis.skills.length > 0 && (
        <details className={own.details}>
          <summary>By concept ({diagnosis.skills.length})</summary>
          <ul className={styles.diagnosisList}>
            {diagnosis.skills.map((skill) => (
              <li key={skill.node_id} data-testid={`loop-diagnosis-${skill.node_id}`}>
                <strong>{names.get(skill.node_id) ?? "Concept"}</strong>: {SKILL_COPY[skill.status] ?? "not clear yet"}
                {skill.independent_observations > 0 && (
                  <div>{skill.independent_correct} of {skill.independent_observations} right on your own</div>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
