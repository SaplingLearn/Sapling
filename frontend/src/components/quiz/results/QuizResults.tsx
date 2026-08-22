"use client";

/**
 * The results screen (§5 B3).
 *
 * The point of the screen is the first thing on it: the concept's node, grown
 * from the mastery it had to the mastery it has, inside a still fragment of the
 * tree it lives on. Everything below is the receipt — the score, the XP line
 * when we know it, the questions worth another look, and the three ways out.
 *
 * Two things it deliberately does NOT do:
 *   - It never recomputes a tier from a score except for the ONE value that has
 *     no tier on the wire, `mastery_after` (R-12). The "before" tier is the
 *     server's `mastery_tier`, read off the concept.
 *   - It never dispatches `sapling:graph-changed`. That belongs to
 *     `useQuizSession`, which knows a submit actually landed; a component
 *     firing it on render would repeat it on every re-render of one result
 *     (§4 amendment).
 */

import React from "react";
import { Button } from "@/components/ui";
import { ConceptNeighbourhood } from "@/components/graph/ConceptNeighbourhood";
import { tierFor } from "@/lib/graph/nodeStyle";
import type { NeighbourNode } from "@/lib/graph/neighbourhood";
import { useUser } from "@/context/UserContext";
import { queueOf } from "@/lib/quiz/machine";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import type { QuizSession } from "@/lib/quiz/types";
import { sourceLabel } from "@/lib/quiz/exits";
import { AskPanel } from "../question/AskPanel";
import type { QuizConceptSummary } from "../question/QuizQuestion";
import { MissedList, buildMissedItems, type MissedItem } from "./MissedList";
import "./results.css";

/** The results canvas, §3's third `ConceptNeighbourhood` preset. */
const CANVAS = { width: 640, height: 212, scale: 2.5 } as const;

export interface QuizResultsProps {
  session: QuizSession;
  actions: QuizActions;
  concept: QuizConceptSummary;
  neighbourhood: { siblings: NeighbourNode[] };
  prefersReducedMotion: boolean;
  /**
   * The next concept in the scope queue, named — for the "Next: {concept}"
   * primary exit. `QuizScreen` resolves it from the loaded graph
   * (`proposals.nextConceptInQueue`), which is the only place that has one.
   *
   * `null` means "no name available", which covers a finished queue AND a next
   * id that isn't in the scoped graph. It is a LABEL only: whether that exit
   * renders at all stays `queueOf(session.scope).length > session.queueIndex + 1`.
   * Optional so the current render keeps compiling until it reads this.
   */
  nextConcept?: { id: string; name: string } | null;
}

const pct = (value: number) => Math.round(value * 100);

export function QuizResults({
  session,
  actions,
  concept,
  neighbourhood,
  prefersReducedMotion,
}: QuizResultsProps) {
  // AskPanel needs the viewer's id and the seam (`QuizResultsProps`) is fixed,
  // so it comes off the same context `QuizScreen` reads. The context has a
  // default value, so this is safe outside a provider (an empty id, which the
  // panel treats as "not signed in") rather than a throw.
  const { userId } = useUser();
  const [asking, setAsking] = React.useState<MissedItem | null>(null);
  // The row that opened the panel, so closing it lands back on that button
  // rather than on the document (AskPanel's `returnFocusTo`).
  const askTrigger = React.useRef<HTMLElement | null>(null);

  const result = session.result;
  // `results` is the only phase that renders this screen and the reducer sets
  // `result` on the way in, so this is a guard, not a state.
  if (!result) return null;

  const before = result.mastery_before;
  const after = result.mastery_after;
  const tierBefore = concept.tier;
  const tierAfter = tierFor(after);
  // "grew" is the whole promise of the screen; a mastery that went down still
  // gets an honest verb rather than a cheerful one.
  const verb = after >= before ? "grew" : "moved";
  const growthLabel = `${concept.name} node ${verb} from ${pct(before)}% to ${pct(after)}% mastery`;

  const missed = buildMissedItems(session);
  const isPerfect = missed.length === 0;

  const queue = queueOf(session.scope);
  const hasNext = session.queueIndex + 1 < queue.length;

  const xpDelta = session.xp ? session.xp.after - session.xp.before : null;

  // The course accent, already resolved by `QuizScreen`. An unresolved one
  // falls through to the app accent inside the mark rather than to a literal.
  const courseColor = concept.color || "var(--quiz-accent, var(--accent))";

  return (
    <div className="quiz-results" data-testid="quiz-results">
      {/* Keyed on the attempt so the node grows exactly once per result: a
          re-render (opening a disclosure, the AskPanel) must not replay it,
          and the NEXT attempt's result must. */}
      <div className="quiz-results__graph">
        <ConceptNeighbourhood
          key={session.attemptId ?? concept.id}
          centre={{
            id: concept.id,
            name: concept.name,
            mastery: concept.mastery,
            tier: concept.tier,
          }}
          siblings={neighbourhood.siblings}
          courseColor={courseColor}
          width={CANVAS.width}
          height={CANVAS.height}
          scale={CANVAS.scale}
          centreVariant={{ kind: "growth", before, after }}
          animate={!prefersReducedMotion}
          ariaLabel={growthLabel}
          testid="quiz-results-graph"
        />
      </div>

      {/* R-5: the repetition guard means a "practise what you missed" attempt
          asks different questions. Say so rather than let it read as a bug. */}
      {session.scope.kind === "missed" && (
        <div className="label-micro quiz-results__eyebrow">Focused on what you missed</div>
      )}

      <h2 className="h-serif quiz-results__name">{concept.name}</h2>
      <p className="quiz-results__delta" data-testid="quiz-results-mastery">
        {pct(before)}% → {pct(after)}% · {tierBefore} → {tierAfter}
      </p>

      <div className="quiz-results__rule">
        <span className="quiz-results__score" data-testid="quiz-results-score">
          {result.score} of {result.total} correct
        </span>
        {/* R-9: submit returns no deltas, so the XP line is a separate read.
            If either half of it failed it is omitted — never invented. */}
        {xpDelta !== null && session.xp && (
          <span className="quiz-results__xp" data-testid="quiz-results-xp">
            +{xpDelta} XP · {session.xp.streak}-day streak
          </span>
        )}
      </div>

      {isPerfect ? (
        <p className="quiz-results__perfect" data-testid="quiz-results-perfect">
          Nothing to review — every answer was right. {concept.name} keeps growing on your tree.
        </p>
      ) : (
        <MissedList
          items={missed}
          onAsk={(item, trigger) => {
            askTrigger.current = trigger;
            setAsking(item);
          }}
        />
      )}

      <hr className="quiz-results__divider" />

      <div className="quiz-results__exits" data-testid="quiz-results-exits">
        {hasNext ? (
          <Button
            variant="primary"
            data-testid="quiz-next-concept"
            onClick={() => actions.nextInQueue()}
          >
            {/* The queue holds concept ids and this screen is given only the
                concept it just quizzed, so the next one cannot be named from
                here. TODO(#537-followup: pass the queue's resolved names into
                QuizResults so this reads "Next: {concept} →"). */}
            Next concept →
          </Button>
        ) : missed.length > 0 ? (
          <Button
            variant="primary"
            data-testid="quiz-practise-missed"
            onClick={() => actions.practiseMissed()}
          >
            {missed.length === 1
              ? "Practise the one you missed"
              : `Practise the ${missed.length} you missed`}
          </Button>
        ) : (
          <Button
            variant="primary"
            data-testid="quiz-again"
            onClick={() =>
              actions.start({
                intent: session.intent,
                scope: session.scope,
                conceptId: session.conceptId,
                courseId: session.courseId,
              })
            }
          >
            Keep going — quiz again
          </Button>
        )}

        <Button data-testid="quiz-back-to-source" onClick={() => actions.exit()}>
          {sourceLabel(session.source.kind)}
        </Button>

        <span className="quiz-results__exits-spacer" />

        <Button variant="link" data-testid="quiz-done" onClick={() => actions.exit("/quiz")}>
          Done
        </Button>
      </div>

      {/* One panel for the whole list — the same sheet the question screen
          opens (R-6), seeded from whichever row asked. */}
      {asking && (
        <AskPanel
          open
          onClose={() => setAsking(null)}
          userId={userId}
          conceptName={concept.name}
          courseId={session.courseId}
          courseLabel={concept.courseCode || undefined}
          returnFocusTo={askTrigger}
          seed={{
            stem: asking.stem,
            chosenLabel: asking.chosenLabel,
            chosenText: asking.chosenText,
            correctLabel: asking.correctLabel,
            correctText: asking.correctText,
            explanation: asking.explanation,
          }}
        />
      )}
    </div>
  );
}
