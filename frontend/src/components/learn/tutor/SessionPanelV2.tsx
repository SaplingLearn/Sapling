"use client";
// The session panel, rebuilt (Tutor redesign phase 4, behind `session_v2`;
// design: learn/__fixtures__/session.design.html, the Claude Design board).
// ONE list: each planned concept once, with its level and a bar (the current
// one marked, the ones the plan has passed dimmed), then a link to the map.
// Folded in from the old panel: the separate Skill meters (into the rows),
// the "How these connect" list and the kind line under each name. Moved: the
// due reviews go to the sidebar's Review. Cut: the map and its key (the Tree
// is one link away). The board's "Saved" tab and "See Midterm 2 progress"
// wait for saved artifacts and milestones.
import React from "react";
import { HandoffLink } from "@/components/ui/HandoffLink";
import type { LoopPanelConcept } from "@/lib/api";
import { LEARNING_COPY } from "@/lib/learningCopy";
import { tierWord } from "@/lib/levels";
import { SidebarGlyph } from "./TutorIcons";
import { useFlag } from "@/context/FlagsContext";
import { SAVED_COPY, SavedList, useSessionSaved } from "./saved";
import { masteryTone, meterTier } from "./TutorPages";
import type { PanelConcept } from "./SessionPanel";
import tutorStyles from "./tutor.module.css";
import styles from "./SessionPanelV2.module.css";

export const SESSION_PANEL_COPY = {
  title: "Plan",
  empty: "Your plan shows here once you start it.",
} as const;

export type PanelRowState = "done" | "now" | "next";
export type PanelRow = { id: string; name: string; score: number | null; state: PanelRowState };

/** The plan's concepts with their skill, in plan order: the one being taught
 *  is `now`, the ones before it `done`; with no plan, the concept being taught.
 *  Before teaching (the check-in and the plan) nothing: the plan screen itself
 *  says where the student starts, and the panel would say it twice. */
export function panelRows(plan: readonly LoopPanelConcept[] | null, skills: readonly PanelConcept[], currentNodeId: string | null): PanelRow[] {
  const score = new Map(skills.map((s) => [s.nodeId, s.score]));
  if (!plan || plan.length === 0) {
    if (!currentNodeId) return [];
    return skills.filter((s) => s.nodeId === currentNodeId).map((s) => ({ id: s.nodeId, name: s.name, score: s.score, state: "now" }));
  }
  const at = currentNodeId ? plan.findIndex((c) => c.node_id === currentNodeId) : -1;
  return plan.map((c, i) => ({
    id: c.node_id,
    name: c.concept_name || "Concept",
    score: score.get(c.node_id) ?? null,
    state: i === at ? "now" : at >= 0 && i < at ? "done" : "next",
  }));
}

export function SessionPanelV2({ plan, currentNodeId, skills, skillWords = false, treeHref, showTreeLink, onHide, sessionId = null }: {
  plan: LoopPanelConcept[] | null;
  currentNodeId: string | null;
  skills: PanelConcept[];
  skillWords?: boolean;
  treeHref: string;
  showTreeLink: boolean;
  onHide: () => void;
  /** `saved_items`: the session whose Saved tab shows beside Plan. */
  sessionId?: string | null;
}) {
  const rows = panelRows(plan, skills, currentNodeId);
  const savedOn = useFlag("saved_items") === "on" && !!sessionId;
  const { items: saved } = useSessionSaved(sessionId, savedOn);
  const [tab, setTab] = React.useState<"plan" | "saved">("plan");
  const showing = savedOn ? tab : "plan";
  return (
    <aside data-testid="loop-rail" aria-label="Today's session" className={tutorStyles.panel}>
      <div className={tutorStyles.panelHead}>
        {savedOn ? (
          <div role="tablist" aria-label="Session panel" className={styles.tabs}>
            {(["plan", "saved"] as const).map((t) => (
              <button key={t} type="button" role="tab" id={`tutor-panel-tab-${t}`} aria-selected={showing === t}
                aria-controls="tutor-panel-body" data-testid={`tutor-panel-tab-${t}`} className={styles.tab} onClick={() => setTab(t)}>
                {t === "plan" ? SESSION_PANEL_COPY.title : SAVED_COPY.tab(saved?.length ?? 0)}
              </button>
            ))}
          </div>
        ) : <h2 className="h-serif">{SESSION_PANEL_COPY.title}</h2>}
        <button type="button" className={tutorStyles.iconBtn} onClick={onHide} aria-label="Hide session panel" data-testid="tutor-panel-hide">
          <SidebarGlyph side="right" />
        </button>
      </div>
      <div id="tutor-panel-body" className={`${tutorStyles.panelInner} ${styles.inner}`} data-testid="tutor-panel-v2"
        role={savedOn ? "tabpanel" : undefined} aria-labelledby={savedOn ? `tutor-panel-tab-${showing}` : undefined}>
        {showing === "saved" && sessionId ? <SavedList sessionId={sessionId} /> : rows.length > 0 ? (
          <ol className={styles.rows} aria-label="Concepts in today's plan">
            {rows.map((r) => {
              const tier = meterTier(r.score, skillWords);
              const word = tierWord(tier, skillWords);
              const pct = r.score == null ? 0 : Math.round(Math.max(0, Math.min(1, r.score)) * 100);
              return (
                <li key={r.id} data-testid={`tutor-panel-concept-${r.id}`} data-state={r.state} data-tier={tier}
                  aria-current={r.state === "now" ? "step" : undefined} className={styles.row}>
                  <span className={styles.top}>
                    <span className={styles.name}>{r.name}</span>
                    <span className={styles.word}>{word}</span>
                  </span>
                  <span className={tutorStyles.bar} role="meter" aria-label={`${r.name} skill`} aria-valuetext={word}
                    aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
                    {r.score != null && <i style={{ "--fill": `${pct}%`, "--tone": masteryTone(r.score, skillWords) } as React.CSSProperties} />}
                  </span>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className={styles.empty}>{SESSION_PANEL_COPY.empty}</p>
        )}
        {showTreeLink && (
          <HandoffLink variant="plain" testId="loop-tree-link" href={treeHref} className={styles.mapLink}>
            {LEARNING_COPY.seeOnMap}
          </HandoffLink>
        )}
      </div>
    </aside>
  );
}
