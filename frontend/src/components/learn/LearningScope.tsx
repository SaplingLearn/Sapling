"use client";

import React, { useEffect, useRef, useState } from "react";
import type { LoopDiagnosis, LoopGoal } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import styles from "./LoopLearn.module.css";

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
  const available = new Set(nodes.map((n) => n.id));
  const confirmed = targets.filter((id) => available.has(id));
  const canSave = !busy && (wholeCourse || (!loadingNodes && !nodesError && confirmed.length > 0 && confirmed.length <= 12));
  return (
    <div className={styles.scopeEditor}>
      <form className={`card ${styles.scopeCard}`} aria-label="Learning goal" onSubmit={(event) => {
        event.preventDefault();
        if (canSave) onSave(wholeCourse ? null : { text: text.trim(), target_node_ids: confirmed });
      }}>
        <h2 className="h-serif" style={{ margin: 0, fontSize: 22 }}>What do you want to learn?</h2>
        <p style={{ margin: 0, fontSize: 14, color: "var(--text-dim)" }}>
          Describe your objective, then confirm the concepts it covers. The tutor will check those concepts and their prerequisites.
        </p>
        <label htmlFor="loop-goal-text">Your objective <span style={{ color: "var(--text-muted)" }}>(optional)</span></label>
        <textarea ref={firstField} id="loop-goal-text" data-testid="loop-goal-text" value={text} maxLength={500} rows={3}
          disabled={busy || wholeCourse} className={styles.scopeText} onChange={(event) => setText(event.target.value)}
          placeholder="For example: explain how negative numbers are represented" />
        <fieldset disabled={busy} className={styles.scopeFieldset}>
          <legend>Learning scope</legend>
          <label className={styles.scopeOption}>
            <input type="radio" data-testid="loop-goal-whole-course" name="loop-goal-scope" checked={wholeCourse} onChange={() => setWholeCourse(true)} />
            <span>Explore the whole course</span>
          </label>
          <label className={styles.scopeOption}>
            <input type="radio" data-testid="loop-goal-selected-concepts" name="loop-goal-scope" checked={!wholeCourse} onChange={() => setWholeCourse(false)} />
            <span>Focus on selected concepts</span>
          </label>
        </fieldset>
        {!wholeCourse && (
          <fieldset disabled={busy} className={styles.scopeFieldset}>
            <legend>Confirm target concepts <span style={{ color: "var(--text-muted)" }}>(1–12)</span></legend>
            <p style={{ margin: "4px 0 10px", fontSize: 13, color: "var(--text-dim)" }}>
              Only concepts from this course are listed. Your text does not select concepts automatically.
            </p>
            {loadingNodes && <p role="status">Loading course concepts…</p>}
            {nodesError && <div role="alert"><p>Couldn&apos;t load this course&apos;s concepts.</p>
              <button type="button" data-testid="loop-goal-retry-concepts" className="btn btn--sm" disabled={busy} onClick={onRetryNodes}>Retry course concepts</button></div>}
            <div className={styles.scopeOptions}>
              {nodes.map((node) => (
                <label key={node.id} className={styles.scopeOption}>
                  <input type="checkbox" checked={confirmed.includes(node.id)} data-testid={`loop-goal-target-${node.id}`}
                    disabled={!confirmed.includes(node.id) && confirmed.length >= 12}
                    onChange={(event) => setTargets((current) => event.target.checked
                      ? [...current, node.id] : current.filter((id) => id !== node.id))} />
                  <span>{node.name}</span>
                </label>
              ))}
            </div>
            {nodes.length === 0 && !loadingNodes && !nodesError && <p role="status">No target concepts are available for this course yet. You can explore the whole course or add material in Library.</p>}
            <p role="status" style={{ margin: "10px 0 0", fontSize: 13 }}>{confirmed.length} of 12 selected</p>
          </fieldset>
        )}
        {error && <p role="alert" style={{ margin: 0, color: "var(--err)", fontSize: 14 }}>{error}</p>}
        <div className={styles.scopeActions}>
          <button type="submit" className="btn btn--primary" disabled={!canSave} data-testid="loop-goal-save">{busy ? "Updating check-in…" : "Use this scope"}</button>
          <button type="button" data-testid="loop-goal-cancel" className="btn btn--ghost" disabled={busy} onClick={onCancel}>Cancel</button>
        </div>
        <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>
          Changing scope keeps your earlier evidence. A new check-in may be needed before you start learning.
        </p>
      </form>
    </div>
  );
}

const STOP_COPY: Record<string, string> = {
  session_cap: "The check-in reached its question limit.",
  per_skill_cap: "Some concepts reached their check-in question limit.",
  session_limit: "The check-in reached its question limit.",
  skill_limit: "Some concepts reached their check-in question limit.",
  coverage_limit: "The check-in could not cover every concept.",
  item_bank_exhausted: "Some concepts have no further available check questions.",
  no_items: "Some concepts have no available check questions.",
  no_check_items: "Some concepts have no available check questions.",
  novice_floor: "The check-in found foundational work to start with.",
};

const STATUS_COPY: Record<string, string> = {
  bracketed: "An initial level was bounded by independent answers. This is a starting estimate, not proof of mastery.",
  limited: "The check-in could not bound every concept's level. Untested concepts remain unassessed.",
  in_progress: "Check-in in progress. Independent answers help locate where to start.",
  not_assessed: "These concepts have not been independently assessed in this check-in.",
};
const SKILL_COPY: Record<string, string> = {
  bracketed: "Initial level bounded",
  partial: "Level not yet bounded",
  above_range: "Success at the highest available level; an upper limit was not found",
  below_range: "Foundational practice needed; an independent success level was not found",
  inconsistent: "Mixed evidence; the level is not yet clear",
  untested: "Not assessed",
};

export function DiagnosisSummary({ diagnosis, names }: { diagnosis: LoopDiagnosis | null; names: Map<string, string> }) {
  if (!diagnosis) return null;
  return (
    <section aria-label="Check-in coverage" data-testid="loop-diagnosis" className={styles.diagnosis}>
      <h3 style={{ margin: "0 0 6px", fontSize: 15 }}>Check-in coverage</h3>
      <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>{STATUS_COPY[diagnosis.status] ?? "Check-in evidence is incomplete."}</p>
      {diagnosis.stop_reason && STOP_COPY[diagnosis.stop_reason] && <p style={{ margin: "6px 0 0", fontSize: 13 }}>{STOP_COPY[diagnosis.stop_reason]}</p>}
      {diagnosis.skills.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary>Evidence by concept ({diagnosis.skills.length})</summary>
          <ul className={styles.diagnosisList}>
            {diagnosis.skills.map((skill) => (
              <li key={skill.node_id} data-testid={`loop-diagnosis-${skill.node_id}`}>
                <strong>{names.get(skill.node_id) ?? "Concept"}</strong>: {SKILL_COPY[skill.status] ?? "Evidence incomplete"}
                <div>{skill.independent_correct} independent correct · {skill.independent_incorrect} independent incorrect</div>
                <div>{skill.independent_observations} independent {skill.independent_observations === 1 ? "answer" : "answers"} out of {skill.observations} observations</div>
                <div>
                  {skill.floor_difficulty !== null ? `Independent success at level ${skill.floor_difficulty}. ` : "No independent success level yet. "}
                  {skill.ceiling_difficulty !== null ? `Independent error at level ${skill.ceiling_difficulty}.` : "No independent error level yet."}
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
