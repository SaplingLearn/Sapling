"use client";
// The check-in result and plan, rebuilt (Tutor redesign phase 4, behind
// `plan_v2`; design: learn/__fixtures__/plan.design.html, the Claude Design
// board). One line from the tutor built from the check-in, "Where you're
// starting" (each concept the check-in measured, on the skill ladder), then
// "Today's plan" with ONE label per concept and Start this plan beside Change
// goal. Folded in from the old card: the diagnosis details (into the rows),
// the goal reasons and the separate "How these connect" list (a planned
// prerequisite now reads in its dependent's label: "New, after Hash tables").
// The kind words are the board's ("Quick review", "New", "Practice"),
// planLabels.ts::planKindLabel, which the session panel and the transcript
// ask with the same `plan_v2` switch, so the three never disagree.
import React, { useLayoutEffect, useRef } from "react";
import { motion } from "framer-motion";
import type { LoopDiagnosis, LoopPlanConcept, LoopPlanPrereqEdge, LoopPlanStarting } from "@/lib/api";
import { LEARNING_COPY } from "@/lib/learningCopy";
import { LEVEL_WORDS, levelFor, type SkillLevel } from "@/lib/levels";
import { useFlag } from "@/context/FlagsContext";
import { useMotionPresets } from "@/lib/motion";
import { modalOpen } from "../modalOpen";
import { PlanPanel } from "../PlanPanel";
import { planKindLabel } from "../planLabels";
import { masteryTone } from "../tutor/TutorPages";
import tutorStyles from "../tutor/tutor.module.css";
import styles from "./PlanV2.module.css";

export const PLAN_V2_COPY = {
  starting: "Where you're starting",
  today: "Today's plan",
  thanks: "Thanks.",
  suggest: "Here's where you're starting and what I suggest for today.",
  suggestOnly: "Here's what I suggest for today.",
  changeGoal: "Change goal",
  setGoal: "Set goal",
  building: "Building your plan…",
  failed: "Today's plan didn't load.",
  empty: "Nothing to plan right now. Ask the tutor anything.",
} as const;

/** "A", "A and B", "A, B and C". */
export function nameList(names: readonly string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** A planned concept's label. New material whose prerequisite comes earlier
 *  in today's plan says so ("New, after Hash tables", the nearest such one);
 *  a kind this client does not know has no label. */
export function planRowLabel(plan: readonly LoopPlanConcept[], index: number, edges: readonly LoopPlanPrereqEdge[]): string | null {
  const c = plan[index];
  const base = planKindLabel(c.kind, true);
  if (c.kind !== "new") return base;
  const before = new Map(plan.slice(0, index).map((p, i) => [p.node_id, i]));
  const prereqs = edges
    .filter((e) => e.dependent === c.node_id && e.prerequisite !== c.node_id && before.has(e.prerequisite))
    .sort((a, b) => (before.get(b.prerequisite) ?? 0) - (before.get(a.prerequisite) ?? 0));
  const first = prereqs[0] ? plan[before.get(prereqs[0].prerequisite) ?? 0] : null;
  return first ? `${base}, after ${first.concept_name || "the concept before it"}` : base;
}

export type StartRow = { id: string; name: string; level: SkillLevel; p: number | null };

/** Every concept the check-in covered, in today's plan order (the rest after,
 *  as the diagnosis lists them). A concept it measured reads the planner's
 *  belief on the ladder; one it never reached is Not started, never the prior. */
export function startingRows(
  diagnosis: LoopDiagnosis | null,
  starting: readonly LoopPlanStarting[],
  plan: readonly LoopPlanConcept[] | null,
  names: Map<string, string>,
): StartRow[] {
  if (!diagnosis) return [];
  const p = new Map(starting.map((s) => [s.node_id, s.p_known]));
  const at = new Map((plan ?? []).map((c, i) => [c.node_id, i]));
  const label = new Map((plan ?? []).map((c) => [c.node_id, c.concept_name]));
  const rows = diagnosis.skills.map((s, i) => {
    const belief = s.observations > 0 ? p.get(s.node_id) ?? null : null;
    return {
      row: { id: s.node_id, name: label.get(s.node_id) || names.get(s.node_id) || "A concept", level: levelFor(belief), p: belief },
      order: at.get(s.node_id) ?? (at.size + i),
    };
  });
  return rows.sort((a, b) => a.order - b.order).map((r) => r.row);
}

/** The tutor's one line, in the ladder's words: a head start (Developing or
 *  Proficient), just getting started (measured, below 30%), new (never
 *  answered); no check-in: just the suggestion. A measured concept is never
 *  called new. */
export function planIntro(rows: readonly StartRow[]): string {
  if (rows.length === 0) return PLAN_V2_COPY.suggestOnly;
  const named = (...levels: string[]) => rows.filter((r) => levels.includes(r.level)).map((r) => r.name);
  const ahead = named("develop", "profic");
  const early = named("novice");
  const fresh = named("not_started");
  const parts: string[] = [PLAN_V2_COPY.thanks];
  if (ahead.length) parts.push(`You have a head start on ${nameList(ahead)}.`);
  if (early.length) parts.push(`You're just getting started on ${nameList(early)}.`);
  if (fresh.length) parts.push(`${nameList(fresh)} ${fresh.length === 1 ? "is" : "are"} new to you.`);
  parts.push(PLAN_V2_COPY.suggest);
  return parts.join(" ");
}

function StartingRow({ row }: { row: StartRow }) {
  const word = LEVEL_WORDS[row.level];
  const pct = row.p == null ? 0 : Math.round(Math.max(0, Math.min(1, row.p)) * 100);
  return (
    <li className={styles.startRow} data-testid={`loop-plan-start-${row.id}`} data-level={row.level}>
      <span className={styles.name}>{row.name}</span>
      <span className={tutorStyles.bar} role="meter" aria-label={`${row.name} skill`} aria-valuetext={word}
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        {row.p != null && <i style={{ "--fill": `${pct}%`, "--tone": masteryTone(row.p, true) } as React.CSSProperties} />}
      </span>
      <span className={styles.word}>{word}</span>
    </li>
  );
}

/** Whether the goal editor's opener is locked: any request in flight, the
 *  scope not loaded, or a grade waiting to be saved. */
export function goalLocked(reasons: readonly boolean[]): boolean {
  return reasons.some(Boolean);
}

export function PlanV2({
  plan, prereqEdges, starting, busy, loadFailed, onApprove, onRetry, diagnosis, names, goal, goalRef,
}: {
  diagnosis: LoopDiagnosis | null;
  names: Map<string, string>;
  plan: LoopPlanConcept[] | null;
  prereqEdges: LoopPlanPrereqEdge[];
  /** GET /plan `starting`: the planner's belief per concept the check-in measured. */
  starting: LoopPlanStarting[];
  busy: boolean;
  loadFailed: boolean;
  onApprove: () => void;
  onRetry: () => void;
  /** Change goal: the goal editor the header's Edit goal opens. */
  goal: { has: boolean; disabled: boolean; open: () => void };
  /** Change goal's button, which takes focus back when the editor is cancelled. */
  goalRef: React.Ref<HTMLButtonElement>;
}) {
  // spec §13 A135: the plan replaces the check-in, so its first line takes focus.
  const leadRef = useRef<HTMLParagraphElement>(null);
  useLayoutEffect(() => {
    if (!modalOpen()) leadRef.current?.focus();
  }, []);
  const m = useMotionPresets();
  const item = m.list.item;
  // Nothing about the start is said until the plan (and its `starting`) has
  // landed: a row read before it would call a measured concept Not started.
  const rows = plan === null ? [] : startingRows(diagnosis, starting, plan, names);
  const lead = plan !== null ? planIntro(rows) : loadFailed ? PLAN_V2_COPY.failed : PLAN_V2_COPY.building;
  return (
    <div className={styles.root} data-testid="loop-plan-v2">
      <motion.div className={styles.col} variants={m.list.container} initial="hidden" animate="shown">
        {/* Focused on arrival; polite, so the line that replaces "Building your plan…" is read out. */}
        <motion.p variants={item} ref={leadRef} tabIndex={-1} aria-live="polite" className={styles.lead} data-testid="loop-plan-intro">
          {lead}
        </motion.p>
        {rows.length > 0 && (
          <motion.section variants={item} aria-labelledby="loop-plan-start-heading" className={styles.starting} data-testid="loop-plan-starting">
            <h2 id="loop-plan-start-heading" className={`h-serif ${styles.h2}`}>{PLAN_V2_COPY.starting}</h2>
            <ul className={styles.startList}>
              {rows.map((r) => <StartingRow key={r.id} row={r} />)}
            </ul>
          </motion.section>
        )}
        <motion.section variants={item} aria-labelledby="loop-plan-heading" className={styles.card}>
          <h2 id="loop-plan-heading" className={`h-serif ${styles.h2}`}>{PLAN_V2_COPY.today}</h2>
          {plan === null && loadFailed && (
            <div className={`${styles.status} ${styles.failed}`}>
              <button data-testid="loop-plan-retry" className="btn btn--sm" onClick={onRetry}>Try again</button>
            </div>
          )}
          {plan !== null && plan.length === 0 && <p className={styles.status}>{PLAN_V2_COPY.empty}</p>}
          {plan && plan.length > 0 && (
            <ol aria-label="Concepts in today's plan" className={styles.planList}>
              {plan.map((c, i) => {
                const label = planRowLabel(plan, i, prereqEdges);
                return (
                  <li key={c.node_id} data-testid={`loop-plan-concept-${c.node_id}`} className={styles.planRow}>
                    <span className={styles.num} aria-hidden>{i + 1}</span>
                    <span className={styles.name}>{c.concept_name || "Concept"}</span>
                    {label && <span data-testid={`loop-plan-kind-${c.node_id}`} className={styles.word}>{label}</span>}
                  </li>
                );
              })}
            </ol>
          )}
          <div className={styles.actions}>
            {plan && plan.length > 0 && (
              <button data-testid="loop-plan-approve" className="btn btn--primary" disabled={busy} onClick={onApprove}>
                {busy ? "Saving…" : LEARNING_COPY.startPlan}
              </button>
            )}
            <button ref={goalRef} type="button" data-testid="loop-set-goal" className="btn"
              disabled={goal.disabled} onClick={goal.open}>
              {goal.has ? PLAN_V2_COPY.changeGoal : PLAN_V2_COPY.setGoal}
            </button>
          </div>
        </motion.section>
      </motion.div>
    </div>
  );
}

/** The plan phase's card: the rebuilt plan with `plan_v2` on, else the plan
 *  card as before (the flag read lives here, out of LoopLearn). */
export function PlanSlot(props: React.ComponentProps<typeof PlanV2>) {
  if (useFlag("plan_v2") !== "on") {
    const { goal: _goal, goalRef: _goalRef, starting: _starting, ...old } = props;
    return <PlanPanel {...old} />;
  }
  return <PlanV2 {...props} />;
}
