"use client";

/**
 * "Choose a topic" — the right-hand column of quiz home.
 *
 * Every concept on the tree, always in view beside the proposal, so choosing
 * something else is one click rather than a detour through a separate screen
 * (it replaced the old "Pick something specific →" list). Concepts are grouped
 * under their course, and a course heading is drawn only when there is more
 * than one: with a single course it would label the whole column with the
 * obvious.
 *
 * Within a course the order is weakest first, the same order the proposal is
 * ranked by, so the top of the list is what the student most likely wants.
 *
 * Each row is a real `<button>` and opens the Concept dialog rather than
 * starting immediately: a concept chosen from a list of forty is exactly the
 * moment to show what it is and what the quiz will be.
 */

import React from "react";
import { ConceptNode } from "@/components/graph/ConceptNode";
import type { EnrolledCourse } from "@/lib/api";
import type { GraphNode } from "@/lib/types";
import { colorFor, metaLine } from "@/lib/quiz/proposals";

/** Diameters from the design; the tokens live in `home.css`. */
const COURSE_DOT = 9;
const ROW_DOT = 14;

export interface TopicListProps {
  groups: { course: EnrolledCourse; nodes: GraphNode[] }[];
  onPick: (nodeId: string) => void;
}

function weakestFirst(a: GraphNode, b: GraphNode): number {
  if (a.mastery_score !== b.mastery_score) return a.mastery_score - b.mastery_score;
  return a.concept_name.localeCompare(b.concept_name);
}

export function TopicList({ groups, onPick }: TopicListProps) {
  const headed = groups.length > 1;
  return (
    <div className="quiz-home__topics" data-testid="quiz-pick-list">
      {groups.map(({ course, nodes }) => {
        const color = colorFor(nodes[0], course);
        return (
          <section key={course.course_id} aria-label={headed ? undefined : course.course_name}>
            {headed && (
              <div className="quiz-home__pick-group">
                {/* `dot`, not the default `node`: the course mark is a flat
                    circle, and the glow the node variant adds reads as a halo. */}
                <ConceptNode
                  size={COURSE_DOT}
                  variant={{ kind: "dot" }}
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
            )}

            {nodes
              .slice()
              .sort(weakestFirst)
              .map(node => (
                <button
                  key={node.id}
                  type="button"
                  className="quiz-home__row"
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
