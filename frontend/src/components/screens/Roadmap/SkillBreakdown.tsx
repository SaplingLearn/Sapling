"use client";

/**
 * The sidebar skill breakdown — one segmented bar per topic, one segment per
 * subtopic (spec §4, reference image 2).
 *
 * This is the SCANNING view. The accordion in the main column is where a
 * student acts; this is where they see the shape of their weakness in one
 * glance. Both read the same payload, so they cannot disagree.
 *
 * Colour comes from `lib/graph/nodeStyle` — the course hue shaded per node,
 * at the tier's opacity — so a segment here and that concept's node on
 * /tree are the same colour at the same strength. Every segment also carries
 * a count in text and a title, because at this size opacity alone is not a
 * reliable encoding (§3.8).
 */

import React from "react";
import { opacityFor, shadeFor, masteryLabel } from "@/lib/graph/nodeStyle";
import type { RoadmapTopic } from "@/lib/api";

const FALLBACK_HUE = "#4FA574"; // --ld-mid; used when a course has no colour

export function SkillBreakdown({
  topics,
  onSelect,
  activeTopicId,
}: {
  topics: RoadmapTopic[];
  onSelect?: (topicId: string) => void;
  activeTopicId?: string | null;
}) {
  if (!topics.length) return null;

  return (
    <section className="roadmap-breakdown" data-testid="roadmap-skill-breakdown">
      <h3 className="roadmap-breakdown__heading">Skill breakdown</h3>
      <ul className="roadmap-breakdown__list">
        {topics.map(topic => {
          const base = topic.color || FALLBACK_HUE;
          const isActive = activeTopicId === topic.id;
          return (
            <li key={topic.id} className="roadmap-breakdown__row">
              <button
                type="button"
                className={
                  "roadmap-breakdown__button" +
                  (isActive ? " roadmap-breakdown__button--active" : "")
                }
                onClick={() => onSelect?.(topic.id)}
                data-testid={`roadmap-breakdown-${topic.id}`}
              >
                <span className="roadmap-breakdown__name">{topic.concept_name}</span>
                <span className="roadmap-breakdown__bar" aria-hidden="true">
                  {topic.subtopics.map(s => (
                    <span
                      key={s.node_id}
                      className={
                        "roadmap-breakdown__seg" +
                        (s.is_stale ? " roadmap-breakdown__seg--stale" : "")
                      }
                      style={{
                        background: shadeFor(base, s.node_id),
                        opacity: opacityFor(s.tier),
                      }}
                      title={`${s.concept_name} — ${masteryLabel(s.tier, s.is_stale)}`}
                    />
                  ))}
                </span>
                {/* The count is the accessible encoding AND what the
                    reference image shows; it is not decoration. */}
                <span className="roadmap-breakdown__count">
                  {topic.summary.mastered}/{topic.summary.total}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
