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
        {subtopic.is_stale && (
          <span className="roadmap-sub__stale" title="You haven't proved this recently">
            needs review
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
