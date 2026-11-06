"use client";

/**
 * The ordered topic accordion — the main column, and the surface a student
 * ACTS on (spec §4, reference image 1).
 *
 * Order arrives already topologically sorted by the server (§3.2); this
 * component must never re-sort, or the "start here" marker would point at a
 * different row than the one the ordering chose.
 *
 * Each subtopic row carries Learn and Quiz (§3.15) — the same two actions
 * the Tree detail panel offers, built with the same href helpers so the
 * routing cannot drift.
 *
 * `order_roadmap` detects prerequisite cycles at THREE levels — topics
 * against each other, subtopics within one topic, and the unfiled list — and
 * merges them into one `cycle_node_ids` set, so `in_cycle` arrives on every
 * row as well as every topic. Both levels are marked here: the topic note
 * says the TOPIC's position is a guess, `SubtopicCycleNote` says the order
 * WITHIN it is, and the per-row badge names which rows are involved. Marking
 * only the topic left a detected subtopic cycle rendering as a confident
 * sequence — the exact thing the ordering code refuses to assert.
 */

import React from "react";
import { useRouter } from "next/navigation";
import { glyphFor, masteryLabel, opacityFor, shadeFor } from "@/lib/graph/nodeStyle";
import { learnHrefForNode } from "@/lib/data";
import { buildQuizHref } from "@/lib/quiz/source";
import type { RoadmapSubtopic, RoadmapTopic } from "@/lib/api";

const FALLBACK_HUE = "#4FA574";

function SubtopicRow({
  subtopic,
  courseId,
  baseHue,
}: {
  subtopic: RoadmapSubtopic;
  courseId: string;
  baseHue: string;
}) {
  const router = useRouter();
  const returnTo = `/roadmap/${courseId}`;

  const learn = () =>
    router.push(
      learnHrefForNode({
        name: subtopic.concept_name,
        course_id: courseId,
        is_subject_root: false,
      }),
    );

  const quiz = () =>
    router.push(
      buildQuizHref(
        { concept: subtopic.node_id },
        { kind: "tree", returnTo },
      ),
    );

  return (
    <li className="roadmap-sub" data-testid={`roadmap-subtopic-${subtopic.node_id}`}>
      <div className="roadmap-sub__head">
        {/* Glyph first: the tier must survive greyscale and small sizes,
            which opacity alone does not (§3.8). */}
        <span
          className="roadmap-sub__glyph"
          style={{ color: shadeFor(baseHue, subtopic.node_id) }}
          aria-hidden="true"
        >
          {glyphFor(subtopic.tier)}
        </span>
        <span className="roadmap-sub__name">{subtopic.concept_name}</span>
        {/* One right-aligned group: a row can be stale AND in a cycle, and
            two independently auto-margined badges would drift apart. */}
        {(subtopic.is_stale || subtopic.in_cycle) && (
          <span className="roadmap-sub__flags">
            {subtopic.is_stale && (
              <span className="roadmap-sub__stale" title="You haven't proved this recently">
                needs review
              </span>
            )}
            {subtopic.in_cycle && (
              <span
                className="roadmap-sub__cycle"
                // Own testid: the sr-only line below deliberately repeats
                // this phrase, so locating the badge by its text is a strict
                // mode violation rather than a locator.
                data-testid="roadmap-cycle-badge"
                title="This concept's prerequisites loop, so where it sits in this list is a guess"
              >
                order unclear
              </span>
            )}
          </span>
        )}
      </div>

      <div className="roadmap-sub__body">
        <span className="roadmap-sub__bar" aria-hidden="true">
          <span
            className="roadmap-sub__fill"
            style={{
              width: `${Math.round(subtopic.mastery * 100)}%`,
              background: shadeFor(baseHue, subtopic.node_id),
              opacity: opacityFor(subtopic.tier),
            }}
          />
        </span>
        <span className="sr-only">
          {subtopic.concept_name}: {masteryLabel(subtopic.tier, subtopic.is_stale)},{" "}
          {Math.round(subtopic.mastery * 100)} percent
          {subtopic.in_cycle ? ", order unclear" : ""}
        </span>

        <span className="roadmap-sub__actions">
          <button type="button" className="btn btn--sm" onClick={learn}>
            Learn
          </button>
          <button type="button" className="btn btn--sm btn--primary" onClick={quiz}>
            Quiz
          </button>
        </span>
      </div>
    </li>
  );
}

/**
 * One note for a whole list whose internal order loops (§3.2).
 *
 * Stated once per list rather than once per row: a cycle is a property of a
 * SET of concepts, so repeating the same sentence on each member would say
 * nothing extra and bury the rows it describes. The per-row "order unclear"
 * badge names which members are involved; this says what that means.
 *
 * Renders nothing when no row is in a cycle, so both callers can mount it
 * unconditionally.
 */
export function SubtopicCycleNote({
  subtopics,
  within,
}: {
  subtopics: RoadmapSubtopic[];
  within: string;
}) {
  if (!subtopics.some(s => s.in_cycle)) return null;
  return (
    <p className="roadmap-topic__cycle" data-testid="roadmap-subtopic-cycle">
      Some concepts below have looping prerequisites, so their order {within} is a
      guess.
    </p>
  );
}

export function TopicAccordion({
  topics,
  courseId,
  startHereTopicId,
  expanded,
  onToggle,
}: {
  topics: RoadmapTopic[];
  courseId: string;
  startHereTopicId: string | null;
  expanded: Set<string>;
  onToggle: (topicId: string) => void;
}) {
  return (
    <ol className="roadmap-topics" data-testid="roadmap-topics">
      {topics.map(topic => {
        const base = topic.color || FALLBACK_HUE;
        const isOpen = expanded.has(topic.id);
        const isStart = topic.id === startHereTopicId;

        return (
          <li
            key={topic.id}
            className={"roadmap-topic" + (isStart ? " roadmap-topic--start" : "")}
            data-testid={`roadmap-topic-${topic.id}`}
          >
            {isStart && (
              <p className="roadmap-topic__startflag" data-testid="roadmap-start-here">
                Start here
              </p>
            )}

            <button
              type="button"
              className="roadmap-topic__header"
              // Own testid: once a topic expands, its subtopics' Learn/Quiz
              // buttons are also buttons inside `roadmap-topics`, so a
              // role-based locator would match them too.
              data-testid="roadmap-topic-header"
              aria-expanded={isOpen}
              onClick={() => onToggle(topic.id)}
            >
              <span className="roadmap-topic__chevron" aria-hidden="true">
                {isOpen ? "▾" : "▸"}
              </span>
              <span className="roadmap-topic__name">{topic.concept_name}</span>

              <span className="roadmap-topic__segs" aria-hidden="true">
                {topic.subtopics.map(s => (
                  <span
                    key={s.node_id}
                    className={
                      "roadmap-topic__seg" +
                      (s.is_stale ? " roadmap-topic__seg--stale" : "")
                    }
                    style={{
                      background: shadeFor(base, s.node_id),
                      opacity: opacityFor(s.tier),
                    }}
                  />
                ))}
              </span>

              <span className="roadmap-topic__count">
                {topic.summary.mastered}/{topic.summary.total}
              </span>
            </button>

            {/* A cycle is not an error the student caused, and the order
                inside it is arbitrary rather than wrong — say exactly that
                instead of silently presenting a confident sequence. */}
            {topic.in_cycle && (
              <p className="roadmap-topic__cycle">
                This topic&apos;s prerequisites loop, so its position here is a guess.
              </p>
            )}

            {isOpen && <SubtopicCycleNote subtopics={topic.subtopics} within="here" />}

            {isOpen && (
              <ul className="roadmap-topic__subs">
                {topic.subtopics.map(s => (
                  <SubtopicRow
                    key={s.node_id}
                    subtopic={s}
                    courseId={courseId}
                    baseHue={base}
                  />
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ol>
  );
}

export { SubtopicRow };
