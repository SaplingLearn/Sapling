"use client";

/**
 * The Concept dialog (§5 B1.5) — what opens when you pick a concept off "Also
 * worth a look" or out of the pick list.
 *
 * It is the proposal card again at dialog scale: the same name / meta /
 * rationale / definition / neighbourhood, plus the three settings rows and a
 * Start that carries the choices made in it. Nothing is committed until Start:
 * the config lives in local state seeded from the session, so Cancel really
 * does discard.
 *
 * The definition is R-8 for THIS concept: `concept-description` is fetched on
 * open (the hook `useQuizHome` describes only the concept the card shows), with
 * a built sentence showing while it is in flight and after a failure. The
 * dialog never blocks on it.
 */

import React from "react";
import Dialog from "@/components/Dialog";
import { Button } from "@/components/ui";
import { ConceptNeighbourhood } from "@/components/graph/ConceptNeighbourhood";
import type { NeighbourNode } from "@/lib/graph/neighbourhood";
import { describeConcept } from "@/lib/quiz/api";
import type { SessionConfig } from "@/lib/quiz/machine";
import { metaLine, type Candidate } from "@/lib/quiz/proposals";
import type { QuizConfig } from "@/lib/quiz/types";
import { QuizSettings } from "./QuizSettings";
import { accentStyle } from "./accent";

/** The dialog's canvas, per §3. */
const CANVAS = { width: 300, height: 200, scale: 2 } as const;

/**
 * The stand-in definition, minus everything the meta line directly above it
 * already says.
 *
 * `useQuizHome.fallbackDefinition` is "{CODE} · {tier} · {n} connected
 * concepts", which on the card sits under a meta line that carries neither the
 * code nor (visibly) the tier. In the dialog the meta IS "{CODE} · {pct}% ·
 * {tier} · {when}", so the built sentence opened the panel by repeating its own
 * first two thirds. Only the connection count is new, so only the connection
 * count is said.
 */
function connectionsLine(connected: number): string {
  if (connected === 0) return "Not yet connected to anything else on your tree.";
  return `${connected} connected ${connected === 1 ? "concept" : "concepts"} on your tree.`;
}

export interface ConceptDialogProps {
  open: boolean;
  userId: string;
  candidate: Candidate;
  siblings: NeighbourNode[];
  /** Edges touching this concept — the `n` in the fallback definition. */
  connected: number;
  config: QuizConfig | null;
  /** The settings the dialog opens on. */
  initialConfig: SessionConfig;
  onCancel: () => void;
  onStart: (config: SessionConfig) => void;
}

/**
 * The AI one-liner for one concept (R-8). Returns `null` while in flight or
 * after a failure — the caller shows the built sentence instead.
 */
function useConceptDescription(
  userId: string,
  open: boolean,
  conceptName: string,
  courseLabel?: string,
): string | null {
  const [text, setText] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open || !userId || !conceptName) return;
    let cancelled = false;
    describeConcept(userId, conceptName, courseLabel).then(
      description => {
        const trimmed = description.trim();
        if (!cancelled && trimmed) setText(trimmed);
      },
      () => {
        // The built sentence stands. A missing definition must never hold up
        // the Start button.
      },
    );
    return () => {
      cancelled = true;
    };
  }, [userId, open, conceptName, courseLabel]);

  return text;
}

export function ConceptDialog({
  open,
  userId,
  candidate,
  siblings,
  connected,
  config,
  initialConfig,
  onCancel,
  onStart,
}: ConceptDialogProps) {
  const titleId = React.useId();
  const [draft, setDraft] = React.useState<SessionConfig>(initialConfig);

  const { node, course, color } = candidate;
  const description = useConceptDescription(userId, open, node.concept_name, course?.course_code);
  const definition = description ?? connectionsLine(connected);

  // The design prefixes the concept's meta with its course code; `metaLine`
  // itself is unchanged.
  const meta = course ? `${course.course_code} · ${metaLine(node)}` : metaLine(node);

  // For a concept that has never been opened, `rationaleFor` degenerates to
  // "{pct}% · not studied yet" — which is the tail of the meta line directly
  // above it. Every other rationale says something the meta doesn't.
  const neverStudied = !node.times_studied && !node.last_studied_at;

  return (
    <Dialog
      open={open}
      onClose={onCancel}
      size="xl"
      labelledBy={titleId}
      // The design has no × here (and one would land on top of the
      // neighbourhood's top-right node); Cancel is the way out, and Escape and
      // the backdrop still work.
      showCloseButton={false}
    >
      <div className="quiz-home-dialog" style={accentStyle(color)} data-testid="quiz-concept-dialog">
        <div className="quiz-home-dialog__card">
          <div className="quiz-home-dialog__main">
            <h2 className="h-serif quiz-home-dialog__name" id={titleId}>
              {node.concept_name}
            </h2>
            <p className="quiz-home-dialog__meta">{meta}</p>
            {candidate.rationale && !neverStudied && (
              <p className="quiz-home-dialog__rationale">{candidate.rationale}</p>
            )}
            <p className="body-serif quiz-home-dialog__definition">{definition}</p>
          </div>
          <div className="quiz-home__card-divider" />
          <ConceptNeighbourhood
            centre={{
              id: node.id,
              name: node.concept_name,
              mastery: node.mastery_score,
              tier: node.mastery_tier,
            }}
            siblings={siblings}
            courseColor={color}
            width={CANVAS.width}
            height={CANVAS.height}
            scale={CANVAS.scale}
            ariaLabel={`${node.concept_name} and its neighbours on your knowledge tree`}
          />
        </div>

        <QuizSettings config={config} value={draft} onChange={setDraft} />

        <div className="quiz-home-dialog__footer">
          <Button variant="link" data-testid="quiz-concept-cancel" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="primary"
            data-testid="quiz-concept-start"
            onClick={() => onStart(draft)}
          >
            {`Start · ${draft.count} ${draft.difficulty}`}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
