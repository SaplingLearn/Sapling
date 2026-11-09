"use client";

/**
 * Quiz home (§5 B1) — `phase: home | configuring`.
 *
 * Two columns. On the left, one proposal you can start in a single click,
 * with its neighbourhood on the tree drawn underneath. On the right, "Choose a
 * topic": the whole due set as one row, then every concept on the tree. The
 * old screen opened on an empty course/concept dropdown and asked the student
 * to know what they wanted; this one arrives with an answer and keeps every
 * alternative in view.
 *
 * Everything on it is derived, never invented: the ranking is
 * `lib/quiz/proposals` (a cited mirror of `graph_service.get_recommendations`,
 * R-7), the meta and rationale lines are its formatters, the option lists come
 * off `GET /api/quiz/config`, and the marks are the tree's own arithmetic
 * through `ConceptNode`, and the neighbourhood window is the tree's own 2D
 * renderer (`LiveNeighbourhood`).
 *
 * The card has three shapes, chosen by how you arrived (§6): a concept (the
 * default, and every `?concept=` / `?topic=` deep link), a course (`?course=`)
 * and the due set (`?scope=due`). The last two run as a queue of single-concept
 * attempts, because `/generate` is per concept (R-4).
 */

import React from "react";
import { apiToGraphNode } from "@/lib/data";
import type { SessionConfig } from "@/lib/quiz/machine";
import { savePrefs } from "@/lib/quiz/prefs";
import type { EntryRequest } from "@/lib/quiz/source";
import type { QuizConfig, QuizSession } from "@/lib/quiz/types";
import type { QuizHome as QuizHomeData } from "@/lib/quiz/useQuizHome";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";
import { AdjustDialog } from "./AdjustDialog";
import { ResumeStrip, homeColumns, masteredState, stateBody } from "./HomeStates";
import { ProposalCard } from "./ProposalCard";
import { TopicsColumn } from "./TopicsColumn";
import { accentStyle } from "./accent";
import { adjustSubtitle, effectiveConfigFor, homeViewFor, prefsFor } from "./homeView";
import { useHomeCard, useTopicFilter } from "./useHomeCard";
import "./home.css";

export interface QuizHomeProps {
  userId: string;
  home: QuizHomeData;
  config: QuizConfig | null;
  entry: EntryRequest;
  session: QuizSession;
  actions: QuizActions;
  /** The concept picked off the topic list changed (`null`: back to the
   *  suggestion). QuizScreen hands it to the home hook, which describes it. */
  onPickedChange?: (conceptId: string | null) => void;
}

export function QuizHome({ home, config, entry, session, actions, onPickedChange }: QuizHomeProps) {
  const reducedMotion = usePrefersReducedMotion();
  const [adjustOpen, setAdjustOpen] = React.useState(false);
  const proposal = useHomeCard({ home, entry, session, actions, onPickedChange, reducedMotion });
  const topics = useTopicFilter(home.byCourse, proposal.mode, proposal.card);

  // ── The little constellation ──────────────────────────────────────────
  //
  // `siblingsFor` works on the adapted `lib/data` node shape (colour resolved,
  // `name` rather than `concept_name`) — the same one the tree feeds its graph,
  // and the one `QuizScreen` already adapts for the results screen.
  const viewNodes = React.useMemo(
    () => home.nodes.map(n => apiToGraphNode(n, home.courses)),
    [home.nodes, home.courses],
  );

  const conceptCount = React.useMemo(
    () => home.nodes.filter(n => !n.is_subject_root).length,
    [home.nodes],
  );

  /** Remember the choices a dialog was started with (§5 B1.6). `setConfig`
   *  persists on its own; `start` does not. */
  const remember = (cfg: SessionConfig) => savePrefs(prefsFor(cfg));

  // ── Dialogs ───────────────────────────────────────────────────────────

  const openAdjust = (open: boolean) => {
    setAdjustOpen(open);
    // `configuring` is the machine's own name for "the adjust dialog is open".
    actions.configure(open);
  };

  // ── Regions ───────────────────────────────────────────────────────────

  const lead = proposal.card ? (
    <ProposalCard
      card={proposal.card}
      proposalRef={proposal.proposalRef}
      entering={proposal.swapped && !reducedMotion}
      showReset={Boolean(proposal.pickedId && proposal.suggested)}
      onPick={proposal.choose}
      title={proposal.title}
      meta={proposal.meta}
      rationale={proposal.rationale}
      definitionPending={proposal.definitionPending}
      definition={proposal.definition}
      configLine={proposal.configLine}
      viewNodes={viewNodes}
      edges={home.edges}
      onStart={() => proposal.startCard(proposal.effectiveConfig)}
      adjustOpen={adjustOpen}
      onAdjust={() => openAdjust(!adjustOpen)}
      dueLink={
        home.due.count > 0 && proposal.mode !== "due"
          ? { count: home.due.count, courseCount: home.due.courseCount }
          : null
      }
      onReviewDue={() =>
        proposal.startQueue("due", proposal.dueQueue, effectiveConfigFor(true, session.config))
      }
    />
  ) : (
    masteredState()
  );

  const side = (
    <TopicsColumn
      byCourse={home.byCourse}
      courseFilter={topics.courseFilter}
      onCourse={topics.setTopicCourse}
      topicQuery={topics.topicQuery}
      onQuery={topics.setTopicQuery}
      topicGroups={topics.topicGroups}
      emptyTopics={topics.emptyTopics}
      onPick={proposal.choose}
      onIntent={home.prefetchDescription}
      returnedId={proposal.returnedId}
    />
  );

  /** Which arrival the screen is rendering. */
  const view = homeViewFor(home.status, home.courses.length, conceptCount);

  return (
    <div className="quiz-home" data-testid="quiz-home" style={accentStyle(proposal.accent)}>
      {home.resumable && (
        <ResumeStrip
          resumable={home.resumable}
          nodes={home.nodes}
          attempts={home.attempts}
          onResume={quizId => actions.resume(quizId)}
          onDiscard={quizId => home.discard(quizId)}
        />
      )}

      {/* A2's `.quiz-body--home` is padding-free so the strip above can bleed;
          everything else gets the column and the page padding back here. The
          two are NESTED rather than stacked on one element: `box-sizing:
          border-box` is global, so a single div carrying both would eat the
          64px of page padding out of the column's measure. The design puts the
          padding outside the column. */}
      <div className="quiz-inset--home">
        <div className="quiz-col quiz-col--home">
          {view === "home"
            ? homeColumns(lead, side)
            : stateBody(view, home.error?.message, () => home.refresh())}
        </div>
      </div>

      {adjustOpen && proposal.card && (
        <AdjustDialog
          open
          subtitle={adjustSubtitle(proposal.conceptName, proposal.courseCode)}
          accent={proposal.accent}
          config={config}
          initialConfig={proposal.effectiveConfig}
          onDone={cfg => {
            openAdjust(false);
            actions.setConfig(cfg);
          }}
          onClose={() => openAdjust(false)}
          onStart={cfg => {
            openAdjust(false);
            remember(cfg);
            proposal.startCard(cfg);
          }}
        />
      )}
    </div>
  );
}
