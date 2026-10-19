"use client";
import React from "react";
import Link from "next/link";

import { SaplingAction, StatusMessage } from "@/components/sapling";
import { goalText, nextStepFor, type LearnerState, type NextStepContext } from "@/lib/dashboard/nextStep";
import styles from "./Dashboard.module.css";

export interface NextStepPanelProps {
  state: LearnerState;
  /** Discovery's last answer is being shown after a failed re-check. */
  stale: boolean;
  ctx: NextStepContext;
  onRetry: () => void;
  onNavigate: (href: string) => void;
  /** No courses: the primary action opens the Courses & Semesters hub. */
  onAddCourse: () => void;
}

/**
 * The saved goal, the ONE next activity, its reason, and one primary action
 * (docs/07 §4 table). Renders only what discovery established; the copy
 * comes from lib/dashboard/nextStep (pure, unit-tested).
 */
export function NextStepPanel({ state, stale, ctx, onRetry, onNavigate, onAddCourse }: NextStepPanelProps) {
  const step = nextStepFor(state, ctx);
  const pending = state.kind === "pending";

  let goal: React.ReactNode;
  if (state.kind === "loop-open") {
    const g = goalText(state.session, ctx);
    goal = (
      <>
        <p className={styles.goalText} data-testid="dashboard-goal-text">{g.text}</p>
        <p className={styles.muted} data-testid="dashboard-goal-scope">
          {[ctx.courseLabel(state.session.courseId), g.scope].filter(Boolean).join(" · ")}
        </p>
      </>
    );
  } else if (state.kind === "loop-none" || state.kind === "no-concepts") {
    goal = (
      <p className={styles.body} data-testid="dashboard-goal-text">
        No saved goal yet. You choose one when you start a check-in.
      </p>
    );
  } else if (state.kind === "no-course") {
    goal = <p className={styles.body} data-testid="dashboard-goal-text">No goal yet — add a course first.</p>;
  } else if (pending) {
    goal = (
      <div aria-hidden="true">
        <div className={styles.pendingLine} />
        <div className={styles.pendingLine} />
      </div>
    );
  } else {
    goal = null; // legacy tutor (no saved goals) or discovery failure
  }

  return (
    <section aria-labelledby="dashboard-next-title" data-testid="dashboard-next" data-state={state.kind} aria-busy={pending || undefined}>
      {goal && (
        <div className={styles.goal} data-testid="dashboard-goal">
          <h2 className={styles.eyebrow}>Your goal</h2>
          {goal}
        </div>
      )}
      <div className={goal ? styles.next : undefined}>
        <p className={styles.eyebrow}>{step.eyebrow}</p>
        <h2 id="dashboard-next-title" tabIndex={-1} className={styles.h2} data-testid="dashboard-next-title">
          {step.title}
        </h2>
        {state.kind === "error" ? (
          <div style={{ marginTop: 12 }}>
            <StatusMessage tone="error" title="Couldn't check your sessions" onRetry={onRetry} testid="dashboard-discovery-error">
              {step.reason}
            </StatusMessage>
          </div>
        ) : (
          step.reason && <p className={styles.body} data-testid="dashboard-next-reason">{step.reason}</p>
        )}
        {step.details.length > 0 && (
          <ul className={styles.details} data-testid="dashboard-next-details">
            {step.details.map((d) => <li key={d}>{d}</li>)}
          </ul>
        )}
        {stale && (
          <div style={{ marginTop: 12 }}>
            <StatusMessage tone="info" onRetry={onRetry} testid="dashboard-discovery-stale">
              Couldn&apos;t re-check your sessions just now; this is what we last found.
            </StatusMessage>
          </div>
        )}
        {pending && (
          <SaplingAction className={styles.primary} disabled data-testid="dashboard-next-action">
            Checking…
          </SaplingAction>
        )}
        {step.action && (
          <SaplingAction
            className={styles.primary}
            onClick={() => onNavigate(step.action!.href)}
            data-testid="dashboard-next-action"
            data-href={step.action.href}
          >
            {step.action.label} <span aria-hidden="true">→</span>
          </SaplingAction>
        )}
        {state.kind === "no-course" && (
          <SaplingAction className={styles.primary} onClick={onAddCourse} data-testid="dashboard-next-action">
            Add a course
          </SaplingAction>
        )}
        {step.links.length > 0 && (
          <div className={styles.linkRow}>
            {step.links.map((l) => (
              <Link key={l.testid} className={styles.textLink} href={l.href} data-testid={l.testid}>
                {l.label} <span aria-hidden="true">↗</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
