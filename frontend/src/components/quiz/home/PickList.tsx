"use client";

/**
 * "Pick something specific" (§5 B1.4) — every concept on the tree, grouped
 * under its course.
 *
 * A browse surface, not a ranking: `groupByCourse` sorts courses by code and
 * concepts by name, so a known name is where you'd look for it. Each row is a
 * real `<button>` — the design draws `div`s with `tabindex`, which is the one
 * thing about it that isn't reproduced (Enter/Space and the focus ring come
 * free from a button and would otherwise have to be hand-wired).
 *
 * Picking a row opens the Concept dialog rather than starting immediately: a
 * concept chosen from a list of forty is exactly the moment to show what it
 * is and what the quiz will be.
 */

import React from "react";
import { Button } from "@/components/ui";
import { ConceptNode } from "@/components/graph/ConceptNode";
import type { EnrolledCourse } from "@/lib/api";
import type { GraphNode } from "@/lib/types";
import { colorFor, metaLine } from "@/lib/quiz/proposals";

/** Diameters from the design; the tokens live in `home.css`. */
const COURSE_DOT = 9;
const ROW_DOT = 14;

export interface PickListProps {
  groups: { course: EnrolledCourse; nodes: GraphNode[] }[];
  onPick: (nodeId: string) => void;
  onBack: () => void;
}

export function PickList({ groups, onPick, onBack }: PickListProps) {
  return (
    <div className="quiz-home__pick" data-testid="quiz-pick-list">
      <Button variant="link" data-testid="quiz-pick-back" onClick={onBack}>
        ← Back
      </Button>
      <div className="label-micro quiz-home__pick-eyebrow">Pick something specific</div>
      <h2 className="h-serif quiz-home__pick-title">What would you like to be tested on?</h2>

      {groups.map(({ course, nodes }) => {
        const color = colorFor(nodes[0], course);
        return (
          <section key={course.course_id}>
            <div className="quiz-home__pick-group">
              <ConceptNode
                size={COURSE_DOT}
                isRoot
                nodeId={`subject_root__${course.course_id}`}
                mastery={0}
                tier="mastered"
                courseColor={color}
              />
              <span className="label-micro">
                {course.course_code} · {course.course_name}
              </span>
            </div>

            {nodes.map(node => (
              <button
                key={node.id}
                type="button"
                className="quiz-home__row quiz-home__row--ruled"
                data-testid={`quiz-pick-${node.id}`}
                onClick={() => onPick(node.id)}
              >
                <span className="quiz-home__row-mark">
                  <ConceptNode
                    size={ROW_DOT}
                    variant={{ kind: "dot" }}
                    nodeId={node.id}
                    mastery={node.mastery_score}
                    tier={node.mastery_tier}
                    courseColor={colorFor(node, course)}
                  />
                </span>
                <span className="h-serif quiz-home__row-name">{node.concept_name}</span>
                <span className="quiz-home__row-spacer" />
                <span className="quiz-home__row-meta">{metaLine(node)}</span>
              </button>
            ))}
          </section>
        );
      })}
    </div>
  );
}
