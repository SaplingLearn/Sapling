"use client";
import React from "react";
import Link from "next/link";

import { SaplingAction } from "@/components/sapling";
import { skillEvidenceLabel } from "@/components/learn/LearningScope";
import { learnHrefForNode, type GraphNode } from "@/lib/data";
import type { GraphNode as ApiNode } from "@/lib/types";
import { TIER_LABEL } from "@/lib/graph/nodeStyle";
import { courseLearnHref, libraryHref, resumeHref, type OpenLoopSession } from "@/lib/dashboard/nextStep";
import { buildQuizHref } from "@/lib/quiz/source";
import { relativeTime } from "./format";
import { StateGlyph, TIERS, tierOf } from "./StateGlyph";
import styles from "./Dashboard.module.css";

/** An open session the student would leave behind by practising elsewhere. */
export interface OpenSessionRef {
  sessionId: string;
  courseId: string | null;
  courseLabel: string | null;
  /** The loop session's goal/progress, when the loop is on and it loaded. */
  loop: OpenLoopSession | null;
}

export interface ConceptDetailProps {
  node: GraphNode;
  /** The wire node (times_studied, last_studied_at) — the evidence source. */
  raw: ApiNode | undefined;
  /** Every node on the map, for a course hub's own counts. */
  nodes: GraphNode[];
  courseLabel: (id: string | null | undefined) => string | null;
  openSession: OpenSessionRef | null;
  onBack: () => void;
  /** Navigate (the page owns the router). */
  onNavigate: (href: string) => void;
  /** Bumped by the page when focus should move to this panel's heading. */
  focusToken?: number;
  /** Heading level: 2 in the page column, 3 inside a titled dialog/sheet. */
  headingLevel?: 2 | 3;
  testid?: string;
}

/**
 * The selected topic (or course hub), beside the map. READ-ONLY: showing,
 * changing or clearing a selection never writes a goal, approves a plan,
 * starts or closes a session, poses a check or grades anything. The only
 * ways out are explicit actions — Practice / Learn in this course (a Learn
 * deep link that keeps the real topic + course ids) and Back.
 *
 * Evidence is only what the graph row and the open session's check-in
 * actually hold; nothing is inferred from the label.
 */
export function ConceptDetail({
  node,
  raw,
  nodes,
  courseLabel,
  openSession,
  onBack,
  onNavigate,
  focusToken,
  headingLevel = 2,
  testid = "dashboard-concept",
}: ConceptDetailProps) {
  const headingRef = React.useRef<HTMLHeadingElement>(null);
  const practiceRef = React.useRef<HTMLButtonElement>(null);
  const [confirming, setConfirming] = React.useState(false);
  const confirmId = React.useId();

  // The page renders this keyed by node id, so a different selection is a
  // fresh panel: an open confirmation never carries over to another topic.

  React.useEffect(() => {
    if (!focusToken) return;
    // After any overlay's own focus restore (it runs on close), then here.
    const t = setTimeout(() => headingRef.current?.focus({ preventScroll: false }), 80);
    return () => clearTimeout(t);
  }, [focusToken]);

  const isHub = !!node.is_subject_root;
  const course = courseLabel(node.course_id) ?? (isHub ? node.name : node.subject) ?? null;
  const tier = tierOf(node.mastery_tier);
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const SubHeading = headingLevel === 2 ? "h3" : "h4";

  const actionHref = isHub ? courseLearnHref(node.course_id) : learnHrefForNode(node);
  const actionLabel = isHub ? `Learn in ${course ?? "this course"}` : "Practice this concept";
  const loop = openSession?.loop ?? null;
  const sameCourse = !!openSession && openSession.courseId === node.course_id;
  // A session that is still settling — a saved answer being checked, or
  // feedback not yet served — is finished first; nothing new starts on top
  // of it (Learn's sessionTransitionBusy / pending-grade guards, #673).
  const settling = loop ? (loop.pendingGrade ? "grade" : loop.phase === "feedback" ? "feedback" : null) : null;

  const startAction = () => {
    if (openSession) setConfirming(true);
    else onNavigate(actionHref);
  };
  const cancel = () => {
    setConfirming(false);
    // Cancel changes nothing; focus goes back to the action it came from.
    setTimeout(() => practiceRef.current?.focus(), 0);
  };

  // ── Evidence (what the stored rows prove, with recency) ──────────────
  const studied = typeof raw?.times_studied === "number" ? raw.times_studied : 0;
  const last = relativeTime(raw?.last_studied_at ?? node.last_studied_at);
  const skill = loop?.diagnosis?.skills.find((s) => s.node_id === node.id) ?? null;
  const inGoal = !!loop?.goal?.target_node_ids.includes(node.id);

  const hubCounts = React.useMemo(() => {
    if (!isHub) return null;
    const own = nodes.filter((n) => !n.is_subject_root && n.course_id === node.course_id);
    const by = Object.fromEntries(TIERS.map((t) => [t, own.filter((n) => tierOf(n.mastery_tier) === t).length]));
    return { total: own.length, by };
  }, [isHub, nodes, node.course_id]);

  return (
    <section className={styles.detail} aria-labelledby={`${testid}-title`} data-testid={testid} data-node-id={node.id}>
      <button type="button" className={`${styles.textLink} ${styles.back}`} onClick={onBack} data-testid={`${testid}-back`}>
        <span aria-hidden="true">←</span> Back to your next step
      </button>
      <p className={styles.eyebrow}>{isHub ? "Selected course" : "Selected concept"}</p>
      <Heading id={`${testid}-title`} ref={headingRef} tabIndex={-1} className={styles.h2}>
        {node.name}
      </Heading>

      {isHub ? (
        <>
          <p className={styles.muted}>Course hub on your map.</p>
          {hubCounts && (
            <p className={styles.body} data-testid={`${testid}-course-counts`}>
              {hubCounts.total === 0
                ? "No concepts on your map for this course yet."
                : `${hubCounts.total} ${hubCounts.total === 1 ? "concept" : "concepts"}: ` +
                  TIERS.map((t) => `${hubCounts.by[t]} ${TIER_LABEL[t].toLowerCase()}`).join(" · ")}
            </p>
          )}
        </>
      ) : (
        <>
          <p className={styles.stateLine} data-testid={`${testid}-state`}>
            {course && <span>{course}</span>}
            <span aria-hidden="true">·</span>
            <span className={styles.stateBadge}>
              <StateGlyph tier={tier} />
              {TIER_LABEL[tier]}
            </span>
          </p>
          <p className={styles.body} data-testid={`${testid}-explanation`}>
            {node.description?.trim() || "No explanation is saved for this concept yet."}
          </p>
          <hr className={styles.rule} />
          <SubHeading className={styles.h3}>Evidence so far</SubHeading>
          <ul className={styles.evidence} data-testid={`${testid}-evidence`}>
            {studied > 0 ? (
              <li>
                {studied} recorded {studied === 1 ? "answer" : "answers"}
                {last ? ` · last ${last}` : ""}
              </li>
            ) : (
              <li>No answers recorded yet — this state is a starting estimate, not evidence of what you know.</li>
            )}
            {skill && <li>Check-in: {skillEvidenceLabel(skill.status)}</li>}
            {inGoal && <li>Part of your saved goal.</li>}
          </ul>
          <p className={styles.muted}>
            States change only from graded answers in check-ins, checks and quizzes — not from chat, notes or time spent.
          </p>
        </>
      )}

      <SaplingAction
        ref={practiceRef}
        className={styles.primary}
        onClick={startAction}
        aria-expanded={openSession ? confirming : undefined}
        aria-controls={openSession ? confirmId : undefined}
        data-testid={`${testid}-practice`}
      >
        {actionLabel} <span aria-hidden="true">→</span>
      </SaplingAction>

      {confirming && openSession && (
        <div id={confirmId} className={styles.confirm} role="group" aria-label="Before you leave this page" data-testid={`${testid}-confirm`}>
          <p style={{ margin: 0 }}>
            {settling === "grade"
              ? `Your open session in ${openSession.courseLabel ?? "another course"} has a saved answer that hasn't finished checking. Finish that first; practice is available after.`
              : settling === "feedback"
                ? `Your last answer in ${openSession.courseLabel ?? "another course"} is recorded but its feedback is still pending. Finish it first; practice is available after.`
                : sameCourse
              ? `You already have an open session in ${openSession.courseLabel ?? "this course"}. Learn reopens it first, so nothing you've done is lost; a separate session on this ${isHub ? "course" : "concept"} needs your confirmation there.`
              : `Your open session in ${openSession.courseLabel ?? "another course"} stays saved. ${isHub ? "This opens learning" : `Practising "${node.name}" continues`} in ${course ?? "this course"}.`}
          </p>
          <div className={styles.confirmActions}>
            {settling ? (
              <SaplingAction onClick={() => onNavigate(resumeHref(openSession.sessionId))} data-testid={`${testid}-confirm-settle`}>
                {settling === "grade" ? "Finish checking first" : "Finish feedback first"}
              </SaplingAction>
            ) : (
              <SaplingAction onClick={() => onNavigate(actionHref)} data-testid={`${testid}-confirm-go`}>
                Continue to Learn
              </SaplingAction>
            )}
            <SaplingAction tone="secondary" onClick={cancel} data-testid={`${testid}-confirm-cancel`}>
              Cancel
            </SaplingAction>
          </div>
        </div>
      )}

      <div className={styles.linkRow}>
        {!isHub && (
          <Link
            className={styles.textLink}
            href={buildQuizHref({ concept: node.id }, { kind: "dashboard", returnTo: "/dashboard" })}
            data-testid={`${testid}-quiz`}
          >
            Quiz this concept
          </Link>
        )}
        {node.course_id && (
          <Link className={styles.textLink} href={libraryHref(node.course_id)} data-testid={`${testid}-library`}>
            Open course Library
          </Link>
        )}
      </div>
      {loop && inGoal && <p className={styles.muted}>Supports your goal. Selecting it here doesn&apos;t change your goal or plan.</p>}
    </section>
  );
}
