"use client";

/**
 * Quiz home's left column: one proposal you can start in a single click, with
 * its neighbourhood on the tree drawn underneath (§5 B1).
 */

import React from "react";
import { Button } from "@/components/ui";
import { Skeleton } from "@/components/Skeleton";
import type { Candidate } from "@/lib/quiz/proposals";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { LiveNeighbourhood } from "./LiveNeighbourhood";

interface CardTextProps {
  /** Show "← Back to the suggestion" (a topic is picked). */
  showReset: boolean;
  onReset: () => void;
  title: string;
  meta: string;
  rationale: string | null;
  definitionPending: boolean;
  definition: string | null;
  configLine: string;
}

function CardText({
  showReset,
  onReset,
  title,
  meta,
  rationale,
  definitionPending,
  definition,
  configLine,
}: CardTextProps) {
  return (
    <div className="quiz-home__card-text">
      {/* No eyebrow: the concept's name heads the card. Once a topic is
          picked, the one line above it is the way back to the suggestion. */}
      {showReset && (
        <div className="quiz-home__eyebrow-row">
          <Button variant="link" data-testid="quiz-pick-reset" onClick={onReset}>
            ← Back to the suggestion
          </Button>
        </div>
      )}
      <div className="h-serif quiz-home__name" data-testid="quiz-proposal-name">
        {title}
      </div>

      {meta && <p className="quiz-home__meta">{meta}</p>}
      {rationale && <p className="quiz-home__rationale">{rationale}</p>}
      {/* Keyed on its text: the AI sentence replacing the built stand-in a
          moment later fades in rather than snapping. */}
      {definitionPending && (
        <div className="quiz-home__definition-pending" data-testid="quiz-definition-pending" aria-hidden>
          <Skeleton width="100%" height={13} />
          <Skeleton width="92%" height={13} />
          <Skeleton width="60%" height={13} />
        </div>
      )}
      {definition && (
        <p className="quiz-home__definition" key={definition}>
          {definition}
        </p>
      )}
      <p className="quiz-home__config">{configLine}</p>
    </div>
  );
}

export interface DueLinkProps {
  count: number;
  courseCount: number;
  onClick: () => void;
}

// The due set is a quiz of its own, so it sits with the card's actions, not
// among the concepts. On a due card the card already IS that quiz.
function DueLink({ count, courseCount, onClick }: DueLinkProps) {
  return (
    <Button
      variant="link"
      className="quiz-home__due"
      data-testid="quiz-review-due"
      onClick={onClick}
    >
      {`Or review everything due · ${count} concepts across ${courseCount} courses →`}
    </Button>
  );
}

export interface ProposalCardProps extends Omit<CardTextProps, "onReset"> {
  card: Candidate;
  proposalRef: React.RefObject<HTMLElement | null>;
  /** Play the card's entrance (a swap, motion allowed). */
  entering: boolean;
  onPick: (nodeId: string | null) => void;
  viewNodes: GraphNode[];
  edges: GraphEdge[];
  onStart: () => void;
  adjustOpen: boolean;
  onAdjust: () => void;
  /** The due link's numbers, or `null` to leave it out. */
  dueLink: Omit<DueLinkProps, "onClick"> | null;
  onReviewDue: () => void;
}

export function ProposalCard({
  card,
  proposalRef,
  entering,
  onPick,
  viewNodes,
  edges,
  onStart,
  adjustOpen,
  onAdjust,
  dueLink,
  onReviewDue,
  ...text
}: ProposalCardProps) {
  return (
    <section
      ref={proposalRef}
      className="quiz-home__proposal"
      data-testid="quiz-proposal"
      data-entering={entering ? "true" : undefined}
    >
      {/* The card's TEXT is keyed on the concept, so a swap remounts it and
          plays its entrance (the first card of a visit arrives without one).
          The neighbourhood below is NOT: it stays mounted, so the concepts
          two neighbourhoods share glide to their new places and the view
          eases onto the new cluster, instead of the graph being rebuilt. */}
      <CardText key={card.node.id} {...text} onReset={() => onPick(null)} />

      <LiveNeighbourhood
        centreId={card.node.id}
        nodes={viewNodes}
        edges={edges}
        onPick={onPick}
        ariaLabel={`${card.node.concept_name} and its neighbours on your knowledge tree`}
      />

      <div className="quiz-home__actions">
        <Button
          variant="primary"
          data-testid="quiz-start"
          onClick={onStart}
        >
          Start
        </Button>
        <Button
          variant="link"
          data-testid="quiz-adjust"
          aria-pressed={adjustOpen}
          data-active={adjustOpen ? "true" : undefined}
          onClick={onAdjust}
        >
          Adjust
        </Button>
      </div>
      {dueLink ? <DueLink {...dueLink} onClick={onReviewDue} /> : null}
    </section>
  );
}
