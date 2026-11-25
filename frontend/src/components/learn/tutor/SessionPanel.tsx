"use client";
import React from "react";
import Link from "next/link";
import type { LoopPanelConcept, LoopPlanPrereqEdge } from "@/lib/api";
import { HANDOFF_COPY } from "@/lib/learningHandoffs";
import { MASTERY_PALETTE, TIER_LABEL, type MasteryTier } from "@/lib/graph/nodeStyle";
import { PlanDeps } from "../PlanDeps";
import { planKind } from "../planLabels";
import { SidebarGlyph } from "./TutorIcons";
import { Meter } from "./TutorPages";
import styles from "./tutor.module.css";

export type PanelConcept = { nodeId: string; name: string; score: number | null };

/** The knowledge map's key: the map is drawn in mastery colours (one colour
 *  per tier, `SessionMap`), so its key is built from the same palette and the
 *  same tier names the map paints with — they cannot drift apart. */
const MAP_TIERS: MasteryTier[] = ["mastered", "learning", "struggling", "unexplored"];

/** The due line: the review queue's own count, else what it holds. */
export function dueCountText(count: number | null): string {
  if (count === null) return "Flashcards and retention checks";
  if (count === 0) return "Nothing due right now";
  return `${count} ${count === 1 ? "review" : "reviews"} due`;
}

/**
 * The session panel (wireframe: "Today's session"): the plan with the concept
 * being taught, a skill meter per concept, what is due for review, and the
 * course's knowledge map. Read-only: every action stays in the conversation.
 */
export function SessionPanel({
  plan,
  prereqEdges = [],
  names,
  currentNodeId,
  skills,
  dueCount,
  dueHref,
  learnerChip,
  hasLearner,
  map,
  treeHref,
  showTreeLink,
  onHide,
}: {
  plan: LoopPanelConcept[] | null;
  /** W3.1: kept GET /plan `prereq_edges` after approve (SessionPanel twin of PlanPanel). */
  prereqEdges?: LoopPlanPrereqEdge[];
  /** Concept id → display name (plan rows + graph); used for edge endpoints. */
  names?: Map<string, string>;
  currentNodeId: string | null;
  skills: PanelConcept[];
  /** Reviews due now in every course (the review queue's count); null: unknown. */
  dueCount: number | null;
  /** Where "Due on Study" goes; null while `hide_study` hides Study. */
  dueHref: string | null;
  learnerChip: React.ReactNode;
  /** The chip has a concept to show (else it keeps its place off screen). */
  hasLearner: boolean;
  map: React.ReactNode;
  treeHref: string;
  /** False on a phone, where the TopBar carries the map link. */
  showTreeLink: boolean;
  onHide: () => void;
}) {
  return (
    <aside data-testid="loop-rail" aria-label="Today's session" className={styles.panel}>
      <div className={styles.panelHead}>
        <h2 className="h-serif">Today&apos;s session</h2>
        <button type="button" className={styles.iconBtn} onClick={onHide} aria-label="Hide session panel" data-testid="tutor-panel-hide">
          <SidebarGlyph side="right" />
        </button>
      </div>
      <div className={styles.panelInner}>
        <div style={hasLearner ? undefined : { display: "none" }}>{learnerChip}</div>
        {plan && plan.length > 0 && (
          <section className={styles.panelSec} aria-labelledby="tutor-panel-plan">
            <span id="tutor-panel-plan" className="label-micro">Plan</span>
            <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
              {plan.map((c, i) => {
                const current = c.node_id === currentNodeId;
                return (
                  <li
                    key={c.node_id}
                    className={`${styles.planRow} ${current ? styles.planCur : ""}`}
                    aria-current={current ? "step" : undefined}
                  >
                    <span className={styles.planBox} aria-hidden>{i + 1}</span>
                    <span className={styles.grow}>
                      <div className={styles.pn}>{c.concept_name || "Concept"}</div>
                      <div className={styles.ps}>{planKind(c.kind)?.label ?? ""}</div>
                    </span>
                  </li>
                );
              })}
            </ol>
            <PlanDeps
              edges={prereqEdges}
              plan={plan}
              names={names ?? new Map()}
              testIdPrefix="session-plan"
            />
          </section>
        )}
        {skills.length > 0 && (
          <section className={styles.panelSec} aria-labelledby="tutor-panel-skill">
            <span id="tutor-panel-skill" className="label-micro">Skill</span>
            {skills.map((s) => <Meter key={s.nodeId} label={s.name} score={s.score} />)}
          </section>
        )}
        {dueHref && (
          <section className={styles.panelSec} aria-labelledby="tutor-panel-due">
            <span id="tutor-panel-due" className="label-micro">Due for review</span>
            <div className={styles.reviewBox}>
              <span data-testid="tutor-panel-due-count" style={{ fontSize: 12, color: "var(--text-muted)" }}>
                {dueCountText(dueCount)}
              </span>
              <Link href={dueHref} className="btn btn--sm" style={{ alignSelf: "flex-start" }} data-testid="tutor-panel-review">
                {HANDOFF_COPY.dueOnStudy}
              </Link>
            </div>
          </section>
        )}
        <section className={styles.panelSec} aria-labelledby="tutor-panel-map">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <span id="tutor-panel-map" className="label-micro">Knowledge map</span>
            {showTreeLink && (
              <Link data-testid="loop-tree-link" href={treeHref} className={styles.textLink} style={{ fontSize: 12 }}>
                {HANDOFF_COPY.seeOnMap}
              </Link>
            )}
          </div>
          {map}
          <ul className={styles.legend} aria-label="Map key" data-testid="tutor-map-key">
            {MAP_TIERS.map((t) => <li key={t}><i style={{ background: MASTERY_PALETTE[t] }} />{TIER_LABEL[t]}</li>)}
            <li data-testid="tutor-map-key-practiced">
              <i className={styles.legendOutline} aria-hidden />
              Practiced
            </li>
          </ul>
        </section>
      </div>
    </aside>
  );
}
