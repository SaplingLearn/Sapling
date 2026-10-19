"use client";
import React from "react";
import { Button, type ButtonProps } from "@/components/ui/Button";
import type { LoopPhase } from "@/lib/api";

/* Shared view primitives for the Learn / Library / Tutor redesign (prompt
 * 01). View-layer only: none of these fetches, owns session state, grades or
 * advances anything. Callers pass real server state and handlers. */

const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

/* ── Surface ─────────────────────────────────────────────────────────── */

/**
 * Opts a subtree into the redesign tokens (sapling.css `.sapling-surface`).
 * `display: contents`, so it adds no layout box and never breaks a flex or
 * height chain; inherited properties and custom properties still flow
 * through it. Portalled overlays (sheets) apply the class themselves.
 */
export function SaplingSurface({ children, testid }: { children: React.ReactNode; testid?: string }) {
  return (
    <div className="sapling-surface" data-sapling-surface="" data-testid={testid} style={{ display: "contents" }}>
      {children}
    </div>
  );
}

/* ── Headings ────────────────────────────────────────────────────────── */

export interface PageHeadingProps {
  /** Context above the title (e.g. "Course library", "Learning studio / CS 101").
   *  Kept separate from the title so the h1 is the page's own name. */
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  /** 1 for the page title (default). Use 2 when the page already owns an h1. */
  level?: 1 | 2;
  testid?: string;
}

export function PageHeading({ eyebrow, title, description, actions, level = 1, testid }: PageHeadingProps) {
  const Title = level === 1 ? "h1" : "h2";
  return (
    <header className="sapling-page-heading" data-testid={testid}>
      <div className="sapling-page-heading__text">
        {eyebrow != null && <p className="sapling-eyebrow">{eyebrow}</p>}
        <Title className="sapling-page-heading__title">{title}</Title>
        {description != null && <p className="sapling-page-heading__description">{description}</p>}
      </div>
      {actions != null && <div className="sapling-page-heading__actions">{actions}</div>}
    </header>
  );
}

export function SectionHeading({ level = 2, children, id, className }: {
  level?: 2 | 3;
  children: React.ReactNode;
  id?: string;
  className?: string;
}) {
  const Tag = level === 2 ? "h2" : "h3";
  return (
    <Tag id={id} className={cx("sapling-section-heading", level === 3 && "sapling-section-heading--h3", className)}>
      {children}
    </Tag>
  );
}

/* ── Actions ─────────────────────────────────────────────────────────── */

export type SaplingActionProps = Omit<ButtonProps, "variant" | "size"> & {
  tone?: "primary" | "secondary" | "quiet";
};

/**
 * The redesign's action button: the existing `ui/Button` (same ref, native
 * <button>, type="button" default) with the 44px-target olive/paper styling.
 */
export const SaplingAction = React.forwardRef<HTMLButtonElement, SaplingActionProps>(function SaplingAction(
  { tone = "primary", className, ...props },
  ref,
) {
  return (
    <Button
      ref={ref}
      variant={tone === "primary" ? "primary" : tone === "quiet" ? "ghost" : "secondary"}
      className={cx("sapling-action", `sapling-action--${tone}`, className)}
      {...props}
    />
  );
});

/* ── Selected state ──────────────────────────────────────────────────── */

export interface SelectableRowProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "type"> {
  selected: boolean;
  testid?: string;
}

/**
 * A material/session row that can be the selected one. Sage fill plus
 * `aria-pressed`, so the state is not conveyed by colour alone. Selected is
 * only "chosen for viewing" — it implies nothing about status or knowledge.
 */
export const SelectableRow = React.forwardRef<HTMLButtonElement, SelectableRowProps>(function SelectableRow(
  { selected, className, testid, children, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      aria-pressed={selected}
      data-selected={selected}
      data-testid={testid}
      className={cx("sapling-selectable", className)}
      {...props}
    >
      {children}
    </button>
  );
});

export interface ChoiceOption {
  /** What onChange reports and the caller submits — e.g. the served answer letter. */
  value: string;
  label: React.ReactNode;
  /** Optional visible key (the served letter), shown in served order. */
  letter?: string;
  testid?: string;
}

export interface ChoiceGroupProps {
  legend: React.ReactNode;
  options: readonly ChoiceOption[];
  value: string | null;
  onChange: (value: string) => void;
  disabled?: boolean;
  /** Extra description ids (e.g. a code block the question refers to). */
  describedBy?: string;
  testid?: string;
}

/**
 * A native radio group: one tab stop, arrow keys move and select, the legend
 * names it. Options render in the order given (served order). The sage fill
 * means SELECTED only — never correct, and it reveals nothing about grading.
 */
export function ChoiceGroup({ legend, options, value, onChange, disabled, describedBy, testid }: ChoiceGroupProps) {
  const name = React.useId();
  return (
    <fieldset className="sapling-choices" disabled={disabled} aria-describedby={describedBy} data-testid={testid}>
      <legend>{legend}</legend>
      {options.map((option) => {
        const selected = value === option.value;
        return (
          <label key={option.value} className="sapling-choice" data-selected={selected} data-testid={option.testid}>
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={selected}
              onChange={() => onChange(option.value)}
            />
            <span>
              {option.letter && <span className="sapling-choice__letter">{option.letter}. </span>}
              {option.label}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

/* ── Goal summary ────────────────────────────────────────────────────── */

export interface GoalSummaryProps {
  /** The persisted, learner-confirmed goal text (or the caller's whole-course wording). */
  goal: React.ReactNode;
  /** The confirmed scope, e.g. "Whole course" or "Functions + Recursion". */
  scope?: React.ReactNode;
  /** Only true when the session allows goal edits (probe/plan). */
  canEdit?: boolean;
  onEdit?: () => void;
  editLabel?: string;
  heading?: string;
  /** Optional caller-rendered control (e.g. one carrying its own test id,
   *  ref and busy state, or a confirmed new-session path while teaching).
   *  When given it replaces the built-in Edit; the caller owns its gating. */
  action?: React.ReactNode;
  testid?: string;
}

/** Read-only by default: the Edit control exists only when BOTH canEdit and
 *  onEdit are given, so a teaching session cannot mutate its goal from here. */
export function GoalSummary({ goal, scope, canEdit = false, onEdit, editLabel = "Edit goal", heading = "Your goal", action, testid }: GoalSummaryProps) {
  const headingId = React.useId();
  return (
    <section className="sapling-goal" aria-labelledby={headingId} data-testid={testid}>
      <div className="sapling-goal__main">
        <h2 id={headingId} className="sapling-eyebrow sapling-goal__eyebrow">{heading}</h2>
        <p className="sapling-goal__text">{goal}</p>
      </div>
      {scope != null && <p className="sapling-goal__scope">Scope: {scope}</p>}
      {action != null
        ? <div className="sapling-goal__action">{action}</div>
        : canEdit && onEdit && (
          <SaplingAction tone="quiet" onClick={onEdit}>{editLabel}</SaplingAction>
        )}
    </section>
  );
}

/* ── Phase strip ─────────────────────────────────────────────────────── */

/** The learner-facing stages over the server's loop phases — the same
 *  grouping LoopLearn's STEPS uses. "Wrap-up", not "Review": closing a
 *  session must not imply a delayed retention check happened. */
export const LOOP_STAGES: readonly { id: string; label: string; phases: readonly LoopPhase[] }[] = [
  { id: "check-in", label: "Check-in", phases: ["probe"] },
  { id: "plan", label: "Plan", phases: ["plan"] },
  { id: "learn", label: "Learn", phases: ["teach", "check", "feedback"] },
  { id: "wrap-up", label: "Wrap-up", phases: ["close"] },
];

/** Index of the stage a server phase belongs to; the `hint` stream phase is a
 *  check. -1 for an unknown/absent phase (nothing is marked current). */
export function stageIndexForPhase(phase: LoopPhase | "hint" | null | undefined): number {
  const p = phase === "hint" ? "check" : phase;
  if (!p) return -1;
  return LOOP_STAGES.findIndex((s) => (s.phases as readonly string[]).includes(p));
}

export function PhaseStrip({ phase, testid }: { phase: LoopPhase | "hint" | null | undefined; testid?: string }) {
  const current = stageIndexForPhase(phase);
  return (
    <ol className="sapling-phases" aria-label="Learning progress" data-testid={testid} data-phase={phase ?? undefined}>
      {LOOP_STAGES.map((stage, i) => {
        const state = current < 0 ? "todo" : i < current ? "done" : i === current ? "current" : "todo";
        return (
          <li key={stage.id} data-state={state} aria-current={state === "current" ? "step" : undefined}>
            <span className="sapling-phases__mark" aria-hidden="true">{state === "done" ? "✓" : i + 1}</span>
            {stage.label}
            {state === "done" && <span className="sapling-visually-hidden"> (completed)</span>}
          </li>
        );
      })}
    </ol>
  );
}

/* ── Status / retry message ──────────────────────────────────────────── */

export interface StatusMessageProps {
  tone?: "info" | "pending" | "success" | "error";
  title?: React.ReactNode;
  children: React.ReactNode;
  /** Show a Retry action. Only pass when a real retry path exists. */
  onRetry?: () => void;
  retryLabel?: string;
  /** While a retry is in flight: the button disables and says so. */
  retrying?: boolean;
  testid?: string;
}

const STATUS_GLYPH: Record<NonNullable<StatusMessageProps["tone"]>, React.ReactNode> = {
  info: <><circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M8 7v4M8 4.5v.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></>,
  pending: <><circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M8 4v4l2.5 1.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></>,
  success: <><circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="m5 8.2 2 2 4-4.2" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></>,
  error: <><path d="M8 1.5 15 14H1Z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /><path d="M8 6v3.5M8 11.5v.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></>,
};

/**
 * Visible explanation plus an operable retry. Errors are `role="alert"`;
 * everything else is a polite `role="status"`. Tone is carried by an icon
 * and the text, never by a red surface.
 */
export function StatusMessage({ tone = "info", title, children, onRetry, retryLabel = "Try again", retrying = false, testid }: StatusMessageProps) {
  return (
    <div
      className={`sapling-status sapling-status--${tone}`}
      role={tone === "error" ? "alert" : "status"}
      data-testid={testid}
    >
      <svg className="sapling-status__icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        {STATUS_GLYPH[tone]}
      </svg>
      <div className="sapling-status__body">
        {title != null && <strong className="sapling-status__title">{title}</strong>}
        {children}
      </div>
      {onRetry && (
        <SaplingAction
          tone="secondary"
          onClick={onRetry}
          disabled={retrying}
          data-testid={testid ? `${testid}-retry` : undefined}
        >
          {retrying ? "Retrying…" : retryLabel}
        </SaplingAction>
      )}
    </div>
  );
}
