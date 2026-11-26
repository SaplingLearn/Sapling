"use client";
import { tierWord } from "@/lib/levels";
import { HandoffLink } from "@/components/ui/HandoffLink";
import React from "react";
import type { LoopPanelConcept, LoopPlanPrereqEdge } from "@/lib/api";
import { LEARNING_COPY } from "@/lib/learningCopy";
import { MASTERY_PALETTE, type MasteryTier } from "@/lib/graph/nodeStyle";
import { PlanDeps } from "../PlanDeps";
import { planKindLabel } from "../planLabels";
import { SidebarGlyph } from "./TutorIcons";
import { Meter } from "./TutorPages";
import styles from "./tutor.module.css";
import { useFlag } from "@/context/FlagsContext";
import { SessionPanelV2 } from "./SessionPanelV2";

/** A key swatch's colour, from the map's own palette (runtime data, not a literal here). */
const swatch = (color: string) => ({ "--swatch": color }) as React.CSSProperties;

export type PanelConcept = { nodeId: string; name: string; score: number | null };

/** The knowledge map's key: the map is drawn in mastery colours (one colour
 *  per tier, `SessionMap`), so its key is built from the same palette and the
 *  same tier names the map paints with — they cannot drift apart. */
const MAP_TIERS: MasteryTier[] = ["mastered", "learning", "struggling", "unexplored"];

/** The due line: the review queue's own count, else what it holds. */
export function dueCountText(count: number | null): string {
  if (count === null) return "Flashcards and retention checks";
  return LEARNING_COPY.reviewsDue(count);
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
  skillWords = false,
  dueCount,
  dueHref,
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
  /** The map and its meters are on the skill ladder (the loop's graph carries
   *  skill, `lib/levels.ts`): the key and the meters say its words. */
  skillWords?: boolean;
  /** Reviews due now in every course (the review queue's count); null: unknown. */
  dueCount: number | null;
  /** Where "Due on Study" goes; null while `hide_study` hides Study. */
  dueHref: string | null;
  map: React.ReactNode;
  treeHref: string;
  /** False on a phone, where the TopBar carries the map link. */
  showTreeLink: boolean;
  onHide: () => void;
}) {
  const boardWords = useFlag("plan_v2") === "on"; // the plan card's words (planKindLabel)
  if (useFlag("session_v2") === "on") { // Tutor redesign phase 4: one list, levels in it
    return <SessionPanelV2 plan={plan} currentNodeId={currentNodeId} skills={skills} skillWords={skillWords}
      treeHref={treeHref} showTreeLink={showTreeLink} onHide={onHide} />;
  }
  return (
    <aside data-testid="loop-rail" aria-label="Today's session" className={styles.panel}>
      <div className={styles.panelHead}>
        <h2 className="h-serif">Today&apos;s session</h2>
        <button type="button" className={styles.iconBtn} onClick={onHide} aria-label="Hide session panel" data-testid="tutor-panel-hide">
          <SidebarGlyph side="right" />
        </button>
      </div>
      <div className={styles.panelInner}>
        {plan && plan.length > 0 && (
          <section className={styles.panelSec} aria-labelledby="tutor-panel-plan">
            <span id="tutor-panel-plan" className="label-micro">Plan</span>
            <ol className={styles.planList}>
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
                      <div className={styles.ps}>{planKindLabel(c.kind, boardWords) ?? ""}</div>
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
            {skills.map((s) => <Meter key={s.nodeId} label={s.name} score={s.score} ladder={skillWords} />)}
          </section>
        )}
        {dueHref && (
          <section className={styles.panelSec} aria-labelledby="tutor-panel-due">
            <span id="tutor-panel-due" className="label-micro">Due for review</span>
            <div className={styles.reviewBox}>
              <span data-testid="tutor-panel-due-count" className={styles.note}>
                {dueCountText(dueCount)}
              </span>
              <HandoffLink size="sm" href={dueHref} className={styles.start} testId="tutor-panel-review">
                {LEARNING_COPY.review}
              </HandoffLink>
            </div>
          </section>
        )}
        <section className={styles.panelSec} aria-labelledby="tutor-panel-map">
          <div className={styles.secHead}>
            <span id="tutor-panel-map" className="label-micro">Knowledge map</span>
            {showTreeLink && (
              <HandoffLink variant="plain" testId="loop-tree-link" href={treeHref} className={`${styles.textLink} ${styles.small}`}>
                {LEARNING_COPY.seeOnMap}
              </HandoffLink>
            )}
          </div>
          {map}
          <ul className={styles.legend} aria-label="Map key" data-testid="tutor-map-key">
            {MAP_TIERS.map((t) => <li key={t}><i style={swatch(MASTERY_PALETTE[t])} />{tierWord(t, skillWords)}</li>)}
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
