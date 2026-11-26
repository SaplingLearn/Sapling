"use client";
import { LEARNING_COPY } from "@/lib/learningCopy";
import { useLayoutEffect, useRef } from "react";
import { motion } from "framer-motion";
import { type LoopDiagnosis, type LoopPlanConcept, type LoopPlanPrereqEdge } from "@/lib/api";
import styles from "./LoopLearn.module.css";
import { DiagnosisSummary } from "./LearningScope";
import { PlanDeps } from "./PlanDeps";
import { planGoalReason, planKind } from "./planLabels";
import { Icon } from "../Icon";
import tutorStyles from "./tutor/tutor.module.css";
import { modalOpen } from "./modalOpen";
import { TutorTurn } from "./TutorTurn";
import { useMotionPresets } from "@/lib/motion";
import planStyles from "./PlanPanel.module.css";

export function PlanPanel({
  plan, prereqEdges = [], busy, loadFailed, onApprove, onRetry, diagnosis, names,
}: {
  diagnosis: LoopDiagnosis | null;
  names: Map<string, string>;
  plan: LoopPlanConcept[] | null;
  /** W3.1: planner prereq pairs among today's proposal ∪ goal targets. */
  prereqEdges?: LoopPlanPrereqEdge[];
  busy: boolean;
  loadFailed: boolean;
  onApprove: () => void;
  onRetry: () => void;
}) {
  // spec §13 A135: the plan replaces the check-in (or its retry), so its heading
  // takes focus — read out, and the place Tab continues from.
  const headingRef = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    if (!modalOpen()) headingRef.current?.focus();
  }, []);
  // The plan's rows arrive one after another when it loads (`list` stagger).
  const m = useMotionPresets();
  return (
    <div className={planStyles.scroll}>
      <div className={tutorStyles.col}>
      <TutorTurn>Here&apos;s today&apos;s plan. Due reviews come first, then what&apos;s new, then related practice.</TutorTurn>
      <section
        aria-labelledby="loop-plan-heading"
        className={`card ${tutorStyles.qcard}`}
      >
        <h2 id="loop-plan-heading" ref={headingRef} tabIndex={-1} className={tutorStyles.cardTitle}>
          Today&apos;s plan
        </h2>
        <DiagnosisSummary diagnosis={diagnosis} names={names} />
        {plan === null && !loadFailed && <div className={planStyles.status}>Building your plan…</div>}
        {plan === null && loadFailed && (
          <div className={`${planStyles.status} ${planStyles.failed}`}>
            <span>Today&apos;s plan didn&apos;t load.</span>
            <button data-testid="loop-plan-retry" className="btn btn--sm" onClick={onRetry}>
              Try again
            </button>
          </div>
        )}
        {plan !== null && plan.length === 0 && (
          <div className={planStyles.status}>Nothing to plan right now — ask the tutor anything.</div>
        )}
        {plan && plan.length > 0 && (
          <motion.ol
            aria-label="Concepts in today's plan"
            className={planStyles.list}
            variants={m.list.container}
            initial="hidden"
            animate="shown"
          >
            {plan.map((c, i) => {
              const kind = planKind(c.kind);
              const why = planGoalReason(c.reason);
              return (
                <motion.li
                  key={c.node_id}
                  variants={m.list.item}
                  data-testid={`loop-plan-concept-${c.node_id}`}
                  className={`${styles.planItem} ${tutorStyles.planRow} ${i === 0 ? tutorStyles.planCur : ""}`}
                >
                  <span className={tutorStyles.planBox} aria-hidden>{i + 1}</span>
                  <span className={planStyles.name}>{c.concept_name || "Concept"}
                    {why && <span data-testid={`loop-plan-reason-${c.node_id}`} className={`${tutorStyles.ps} ${planStyles.reason}`}>{why}</span>}
                  </span>
                  {kind && <span data-testid={`loop-plan-kind-${c.node_id}`} className={kind.chip}>{kind.label}</span>}
                </motion.li>
              );
            })}
          </motion.ol>
        )}
        {plan && plan.length > 0 && (
          <PlanDeps edges={prereqEdges} plan={plan} names={names} testIdPrefix="loop-plan" />
        )}
        {plan && plan.length > 0 && (
          <button
            data-testid="loop-plan-approve"
            className={`btn btn--primary ${planStyles.approve}`}
            disabled={busy}
            onClick={onApprove}
          >
            <Icon name="sparkle" size={14} /> {busy ? "Saving…" : LEARNING_COPY.startPlan}
          </button>
        )}
      </section>
      </div>
    </div>
  );
}
