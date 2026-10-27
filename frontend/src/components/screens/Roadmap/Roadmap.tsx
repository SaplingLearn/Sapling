"use client";

/**
 * The course study roadmap (spec §4).
 *
 * Composes the two reference layouts: an ordered topic accordion in the main
 * column, where the student acts, and a sidebar carrying the readiness ring,
 * the skill breakdown, and the exam list, where the student scans. Both read
 * ONE payload, so the two views cannot disagree about the same concept.
 *
 * Everything numeric is computed by `services/roadmap.py` and rendered here
 * verbatim. This component sorts nothing and derives no mastery.
 */

import React from "react";
import { TopBar } from "@/components/TopBar";
import { useUser } from "@/context/UserContext";
import {
  getRoadmap,
  getRoadmapReadiness,
  type RoadmapReadiness,
  type RoadmapResponse,
} from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";
import { Skeleton } from "@/components/Skeleton";
import { TopicAccordion, SubtopicRow } from "./TopicAccordion";
import { ReadinessRing, examCountdown } from "./ReadinessRing";
import { SkillBreakdown } from "./SkillBreakdown";
import { ReadinessBreakdown } from "./ReadinessBreakdown";
import "./roadmap.css";

const FALLBACK_HUE = "#4FA574";

export function RoadmapScreen({ courseId }: { courseId: string }) {
  const { userId, userReady } = useUser();

  const [data, setData] = React.useState<RoadmapResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [examId, setExamId] = React.useState<string | undefined>(undefined);
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const [why, setWhy] = React.useState<RoadmapReadiness | null>(null);

  React.useEffect(() => {
    if (!userReady || !userId) return;
    let cancelled = false;
    setLoading(true);
    getRoadmap(userId, courseId, examId)
      .then(res => {
        if (cancelled) return;
        setData(res);
        setError(null);
        // Open the topic the ordering says to start with. Opening everything
        // would bury the recommendation; opening nothing makes the first
        // visit a wall of closed rows.
        setExpanded(prev =>
          prev.size ? prev : new Set(res.start_here_topic_id ? [res.start_here_topic_id] : []),
        );
      })
      .catch(e => {
        if (!cancelled) setError(humanizeError(e, "We couldn't load your study plan."));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [userId, userReady, courseId, examId]);

  const toggle = (topicId: string) =>
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(topicId)) next.delete(topicId);
      else next.add(topicId);
      return next;
    });

  const explain = async () => {
    if (!userId) return;
    try {
      setWhy(await getRoadmapReadiness(userId, courseId, examId));
    } catch (e) {
      setError(humanizeError(e, "We couldn't explain that number right now."));
    }
  };

  if (loading && !data) {
    return (
      <>
        <TopBar title="Study plan" />
        <div className="roadmap" data-testid="roadmap-loading">
          <Skeleton height={120} />
          <Skeleton height={220} />
        </div>
      </>
    );
  }

  if (error && !data) {
    return (
      <>
        <TopBar title="Study plan" />
        <div className="roadmap roadmap--error" data-testid="roadmap-error">
          <p>{error}</p>
        </div>
      </>
    );
  }

  if (!data) return null;

  const hasAnything = data.topics.length > 0 || data.unfiled.length > 0;

  return (
    <>
      <TopBar
        title="Study plan"
        subtitle="The topics this course asks of you, and how ready you are for them."
      />

      <div className="roadmap" data-testid="roadmap">
        <div className="roadmap__main">
          {/* No concepts at all — nothing to organise, so don't offer it. */}
          {!hasAnything && (
            <div className="roadmap__empty" data-testid="roadmap-empty">
              <h2>Nothing to plan yet</h2>
              <p>
                Upload this course&apos;s material or start a tutoring session, and the
                concepts you cover will appear here.
              </p>
            </div>
          )}

          {/* Concepts exist but nothing has grouped them (§3.16). The flat
              list is immediately useful, so it leads; organising is offered,
              not demanded. */}
          {data.needs_structure && (
            <div className="roadmap__unstructured" data-testid="roadmap-needs-structure">
              <div className="roadmap__organise">
                <div>
                  <h2>{data.unfiled.length} concepts, not yet grouped</h2>
                  <p>
                    Group them into topics to get an ordered study plan. You&apos;ll review
                    the grouping before anything changes.
                  </p>
                </div>
                {/* Wired in the structure-proposals phase; shown disabled
                    rather than hidden so the path is discoverable. */}
                <button type="button" className="btn btn--primary" disabled>
                  Organise into topics
                </button>
              </div>
            </div>
          )}

          {data.topics.length > 0 && (
            <TopicAccordion
              topics={data.topics}
              courseId={courseId}
              startHereTopicId={data.start_here_topic_id}
              expanded={expanded}
              onToggle={toggle}
            />
          )}

          {/* Unfiled concepts are never hidden — they count toward readiness,
              so hiding them would make the ring unexplainable. */}
          {!data.needs_structure && data.unfiled.length > 0 && (
            <section className="roadmap__unfiled" data-testid="roadmap-unfiled">
              <h2 className="roadmap__unfiled-head">
                Unfiled concepts ({data.unfiled.length})
              </h2>
              <ul className="roadmap-topic__subs">
                {data.unfiled.map(s => (
                  <SubtopicRow
                    key={s.node_id}
                    subtopic={s}
                    courseId={courseId}
                    baseHue={s.color || FALLBACK_HUE}
                  />
                ))}
              </ul>
            </section>
          )}
        </div>

        <aside className="roadmap__side">
          <ReadinessRing
            readiness={data.readiness}
            exam={data.selected_exam}
            onExplain={hasAnything ? explain : undefined}
          />

          <dl className="roadmap__stats">
            <div>
              <dt>Topics</dt>
              <dd>{data.topics.length}</dd>
            </div>
            <div>
              <dt>Started</dt>
              <dd>{data.summary.started}</dd>
            </div>
            <div>
              <dt>Mastered</dt>
              <dd>{data.summary.mastered}</dd>
            </div>
          </dl>

          <SkillBreakdown
            topics={data.topics}
            activeTopicId={data.start_here_topic_id}
            onSelect={topicId => {
              setExpanded(prev => new Set(prev).add(topicId));
              document
                .querySelector(`[data-testid="roadmap-topic-${topicId}"]`)
                ?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
          />

          {data.exams.length > 0 && (
            <section className="roadmap__exams" data-testid="roadmap-exams">
              <h3>Exam dates</h3>
              <ul>
                {data.exams.map(e => (
                  <li key={e.id}>
                    <button
                      type="button"
                      className={
                        "roadmap__exam" +
                        (data.selected_exam?.id === e.id ? " roadmap__exam--active" : "")
                      }
                      onClick={() => setExamId(examId === e.id ? undefined : e.id)}
                    >
                      <span className="roadmap__exam-title">{e.title}</span>
                      <span className="roadmap__exam-when">{examCountdown(e.due_date)}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <p className="roadmap__exams-note">
                Pick an exam to score your readiness against its date.
              </p>
            </section>
          )}
        </aside>
      </div>

      {why && <ReadinessBreakdown data={why} onClose={() => setWhy(null)} />}
    </>
  );
}
