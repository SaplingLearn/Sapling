"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { LoopDiagnosis, LoopGoal } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import { SaplingAction, StatusMessage } from "@/components/sapling";
import styles from "./LoopLearn.module.css";

export function GoalEditor({ goal, nodes, busy, error, onSave, onCancel, loadingNodes = false, nodesError = false, onRetryNodes, libraryLink = "/library" }: {
  goal: LoopGoal | null;
  /** Where "Add material in Library" goes (the caller scopes it to the course). */
  libraryLink?: string;
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
  const headingId = React.useId();
  useEffect(() => { firstField.current?.focus(); }, []);
  const available = new Set(nodes.map((n) => n.id));
  const confirmed = targets.filter((id) => available.has(id));
  const canSave = !busy && (wholeCourse || (!loadingNodes && !nodesError && confirmed.length > 0 && confirmed.length <= 12));
  return (
    <div className={styles.scopeEditor}>
      <form className={styles.goalForm} aria-label="Learning goal" onSubmit={(event) => {
        event.preventDefault();
        if (canSave) onSave(wholeCourse ? null : { text: text.trim(), target_node_ids: confirmed });
      }}>
        <div>
          <p className="sapling-eyebrow">Your goal</p>
          <h2 id={headingId} className={styles.panelTitle}>What do you want to learn?</h2>
          <p className={styles.panelLead}>
            Describe your objective, then confirm the concepts it covers. The tutor will check those concepts and their prerequisites.
          </p>
        </div>
        <div className={styles.field}>
          <label htmlFor="loop-goal-text" className={styles.fieldLabel}>
            Your objective <span className={styles.fieldHint}>(optional)</span>
          </label>
          <textarea ref={firstField} id="loop-goal-text" data-testid="loop-goal-text" value={text} maxLength={500} rows={3}
            disabled={busy || wholeCourse} className={styles.input} onChange={(event) => setText(event.target.value)}
            placeholder="For example: explain how negative numbers are represented" />
          <span className={styles.fieldHint}>{text.length} / 500</span>
        </div>
        <fieldset disabled={busy} className={styles.goalFieldset}>
          <legend className={styles.fieldLabel}>Learning scope</legend>
          <label className={styles.goalOption} data-selected={wholeCourse}>
            <input type="radio" data-testid="loop-goal-whole-course" name="loop-goal-scope" checked={wholeCourse} onChange={() => setWholeCourse(true)} />
            <span>Explore the whole course</span>
          </label>
          <label className={styles.goalOption} data-selected={!wholeCourse}>
            <input type="radio" data-testid="loop-goal-selected-concepts" name="loop-goal-scope" checked={!wholeCourse} onChange={() => setWholeCourse(false)} />
            <span>Focus on selected concepts</span>
          </label>
        </fieldset>
        {!wholeCourse && (
          <fieldset disabled={busy} className={styles.goalFieldset}>
            <legend className={styles.fieldLabel}>Confirm target concepts <span className={styles.fieldHint}>(1–12)</span></legend>
            <p className={styles.fieldHint}>
              Only concepts from this course are listed. Your text does not select concepts automatically.
            </p>
            {loadingNodes && <StatusMessage tone="pending">Loading course concepts…</StatusMessage>}
            {nodesError && (
              <div role="alert" className={styles.inlineError}>
                <p>Couldn&apos;t load this course&apos;s concepts. Your objective is kept.</p>
                <SaplingAction tone="secondary" data-testid="loop-goal-retry-concepts" disabled={busy} onClick={onRetryNodes}>
                  Retry course concepts
                </SaplingAction>
              </div>
            )}
            {nodes.length > 0 && (
              <div className={styles.goalTargets}>
                {nodes.map((node) => {
                  const checked = confirmed.includes(node.id);
                  return (
                    <label key={node.id} className={styles.goalOption} data-selected={checked}>
                      <input type="checkbox" checked={checked} data-testid={`loop-goal-target-${node.id}`}
                        disabled={!checked && confirmed.length >= 12}
                        onChange={(event) => setTargets((current) => event.target.checked
                          ? [...current, node.id] : current.filter((id) => id !== node.id))} />
                      <span>{node.name}</span>
                    </label>
                  );
                })}
              </div>
            )}
            {nodes.length === 0 && !loadingNodes && !nodesError && (
              <div role="status" className={styles.inlineEmpty} data-testid="loop-goal-no-concepts">
                <p>No target concepts are available for this course yet. You can explore the whole course or add material in Library.</p>
                <div className={styles.actionRow}>
                  <SaplingAction tone="secondary" onClick={() => setWholeCourse(true)}>Explore the whole course instead</SaplingAction>
                  <Link href={libraryLink} className={styles.textLink}>Add material in Library</Link>
                </div>
              </div>
            )}
            <p role="status" className={styles.goalCount}>{confirmed.length} of 12 selected</p>
          </fieldset>
        )}
        {error && <StatusMessage tone="error">{error} Your draft is kept.</StatusMessage>}
        <div className={styles.actionRow}>
          <SaplingAction type="submit" disabled={!canSave} data-testid="loop-goal-save">{busy ? "Updating check-in…" : "Use this scope"}</SaplingAction>
          <SaplingAction tone="quiet" data-testid="loop-goal-cancel" disabled={busy} onClick={onCancel}>Cancel</SaplingAction>
        </div>
        <p className={styles.fieldHint}>
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

/** A short, honest label for one concept's check-in evidence (the learning
 *  route uses it). Never a mastery claim; unknown statuses read as incomplete. */
export function skillEvidenceLabel(status: string | undefined): string {
  return status ? SKILL_COPY[status] ?? "Evidence incomplete" : "Not assessed";
}

export function DiagnosisSummary({ diagnosis, names }: { diagnosis: LoopDiagnosis | null; names: Map<string, string> }) {
  if (!diagnosis) return null;
  return (
    <section aria-label="Check-in coverage" data-testid="loop-diagnosis" className={styles.diagnosis}>
      <h3 className={styles.diagnosisTitle}>Check-in coverage</h3>
      <p className={styles.diagnosisText}>{STATUS_COPY[diagnosis.status] ?? "Check-in evidence is incomplete."}</p>
      {diagnosis.stop_reason && STOP_COPY[diagnosis.stop_reason] && <p className={styles.diagnosisText}>{STOP_COPY[diagnosis.stop_reason]}</p>}
      {diagnosis.skills.length > 0 && (
        <details className={styles.diagnosisDetails}>
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
