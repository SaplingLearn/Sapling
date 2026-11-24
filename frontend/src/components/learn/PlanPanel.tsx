"use client";
import { useLayoutEffect, useRef } from "react";
import { type LoopDiagnosis, type LoopPlanConcept, type LoopPlanPrereqEdge } from "@/lib/api";
import styles from "./LoopLearn.module.css";
import { DiagnosisSummary } from "./LearningScope";
import { PlanDeps } from "./PlanDeps";
import { planGoalReason, planKind } from "./planLabels";
import { Icon } from "../Icon";
import tutorStyles from "./tutor/tutor.module.css";
import { modalOpen } from "./modalOpen";
import { TutorTurn } from "./TutorTurn";

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
  return (
    <div style={{ flex: 1, overflowY: "auto" }}>
      <div className={tutorStyles.col}>
      <TutorTurn>Here&apos;s today&apos;s plan. Due reviews come first, then what&apos;s new, then related practice.</TutorTurn>
      <section
        aria-labelledby="loop-plan-heading"
        className={`card ${tutorStyles.qcard}`}
      >
        <div className={tutorStyles.qhead}>
          <h2 id="loop-plan-heading" ref={headingRef} tabIndex={-1} className={`label-micro ${tutorStyles.qlabel}`}>
            Today&apos;s plan
          </h2>
        </div>
        <DiagnosisSummary diagnosis={diagnosis} names={names} />
        {plan === null && !loadFailed && <div style={{ fontSize: 14, color: "var(--text-muted)" }}>Building your plan…</div>}
        {plan === null && loadFailed && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14, color: "var(--text-muted)" }}>
            <span>Today&apos;s plan didn&apos;t load.</span>
            <button data-testid="loop-plan-retry" className="btn btn--sm" onClick={onRetry}>
              Try again
            </button>
          </div>
        )}
        {plan !== null && plan.length === 0 && (
          <div style={{ fontSize: 14, color: "var(--text-muted)" }}>Nothing to plan right now — ask the tutor anything.</div>
        )}
        {plan && plan.length > 0 && (
          <ol aria-label="Concepts in today's plan" style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
            {plan.map((c, i) => {
              const kind = planKind(c.kind);
              const why = planGoalReason(c.reason);
              return (
                <li
                  key={c.node_id}
                  data-testid={`loop-plan-concept-${c.node_id}`}
                  className={`${styles.planItem} ${tutorStyles.planRow} ${i === 0 ? tutorStyles.planCur : ""}`}
                >
                  <span className={tutorStyles.planBox} aria-hidden>{i + 1}</span>
                  <span style={{ flex: "1 1 100px", minWidth: 0, overflowWrap: "anywhere", fontSize: 14, fontWeight: 500 }}>{c.concept_name || "Concept"}
                    {why && <span data-testid={`loop-plan-reason-${c.node_id}`} className={tutorStyles.ps} style={{ display: "block", marginTop: 2, fontWeight: 400 }}>{why}</span>}
                  </span>
                  {kind && <span data-testid={`loop-plan-kind-${c.node_id}`} className={kind.chip}>{kind.label}</span>}
                </li>
              );
            })}
          </ol>
        )}
        {plan && plan.length > 0 && (
          <PlanDeps edges={prereqEdges} plan={plan} names={names} testIdPrefix="loop-plan" />
        )}
        {plan && plan.length > 0 && (
          <button
            data-testid="loop-plan-approve"
            className="btn btn--primary"
            style={{ alignSelf: "flex-start" }}
            disabled={busy}
            onClick={onApprove}
          >
            <Icon name="sparkle" size={14} /> {busy ? "Saving…" : "Start learning"}
          </button>
        )}
      </section>
      </div>
    </div>
  );
}
