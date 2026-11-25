"use client";

/**
 * Quiz home's right column: "Choose a topic" — List (course pills + search +
 * `TopicList`) or Map (`LauncherMap` / KnowledgeGraph2D). One List | Map
 * control; both browse modes feed the same `onPick` → lead card (W7.D3 / W7.10).
 */

import React from "react";
import { Icon } from "@/components/Icon";
import { Pill } from "@/components/Pill";
import { SegmentedControl } from "@/components/ui";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { colorFor } from "@/lib/quiz/proposals";
import type { QuizHome as QuizHomeData } from "@/lib/quiz/useQuizHome";
import { LauncherMap } from "./LauncherMap";
import { TopicList, type TopicListProps } from "./TopicList";

export type BrowseMode = "list" | "map";

interface CoursePillsProps {
  byCourse: QuizHomeData["byCourse"];
  courseFilter: string;
  onCourse: (courseId: string) => void;
}

function CoursePills({ byCourse, courseFilter, onCourse }: CoursePillsProps) {
  return (
    <div className="quiz-home__courses" role="group" aria-label="Show concepts from">
      <Pill
        size="md"
        active={courseFilter === "all"}
        onClick={() => onCourse("all")}
        testId="quiz-course-all"
      >
        All
      </Pill>
      {byCourse.map(({ course, nodes }) => (
        <Pill
          size="md"
          key={course.course_id}
          active={courseFilter === course.course_id}
          onClick={() => onCourse(course.course_id)}
          testId={`quiz-course-${course.course_id}`}
          icon={
            <span
              className="quiz-home__course-dot"
              style={{ "--quiz-home-course-tint": colorFor(nodes[0], course) } as React.CSSProperties}
              aria-hidden
            />
          }
        >
          {course.course_code}
        </Pill>
      ))}
    </div>
  );
}

interface TopicSearchProps {
  topicQuery: string;
  onQuery: (query: string) => void;
}

function TopicSearch({ topicQuery, onQuery }: TopicSearchProps) {
  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape" && topicQuery) {
      e.preventDefault();
      onQuery("");
    }
  };
  return (
    <label className="quiz-home__search">
      <Icon name="search" size={15} />
      <input
        type="search"
        className="quiz-home__search-input"
        data-testid="quiz-topic-search"
        placeholder="Search concepts"
        aria-label="Search your concepts"
        value={topicQuery}
        onChange={e => onQuery(e.target.value)}
        onKeyDown={onKeyDown}
      />
    </label>
  );
}

export interface TopicsColumnProps extends CoursePillsProps, TopicSearchProps {
  topicGroups: TopicListProps["groups"];
  emptyTopics: string;
  onPick: TopicListProps["onPick"];
  onIntent: TopicListProps["onIntent"];
  returnedId: string | null;
  planOf?: TopicListProps["planOf"];
  /** List (default) or Map browse mode over the same concept set (W7.10). */
  browseMode: BrowseMode;
  onBrowseMode: (mode: BrowseMode) => void;
  /** Adapted tree for the Map pane (`lib/data` shape). */
  mapNodes: GraphNode[];
  mapEdges: GraphEdge[];
  /** Lead concept highlighted on the Map. */
  highlightId?: string | null;
}

export function TopicsColumn({
  byCourse,
  courseFilter,
  onCourse,
  topicQuery,
  onQuery,
  topicGroups,
  emptyTopics,
  onPick,
  onIntent,
  returnedId,
  planOf,
  browseMode,
  onBrowseMode,
  mapNodes,
  mapEdges,
  highlightId,
}: TopicsColumnProps) {
  return (
    <section className="quiz-home__topics-col" aria-label="Choose a topic">
      {/* Course pills (2+ courses), List | Map, and — in List mode — search. */}
      <div className="quiz-home__toolbar">
        {byCourse.length > 1 && (
          <CoursePills byCourse={byCourse} courseFilter={courseFilter} onCourse={onCourse} />
        )}
        <SegmentedControl<BrowseMode>
          ariaLabel="Browse concepts as a list or map"
          testid="quiz-browse"
          options={[
            { value: "list", label: "List" },
            { value: "map", label: "Map" },
          ]}
          value={browseMode}
          onChange={onBrowseMode}
        />
        {browseMode === "list" && (
          <TopicSearch topicQuery={topicQuery} onQuery={onQuery} />
        )}
      </div>
      {browseMode === "list" ? (
        /* Capped to the proposal's height and scrolled inside (`home.css`). */
        <div className="quiz-home__topics-scroll">
          {topicGroups.length > 0 ? (
            <TopicList
              groups={topicGroups}
              onPick={onPick}
              onIntent={onIntent}
              returnedId={returnedId}
              planOf={planOf}
            />
          ) : (
            <p className="quiz-home__topics-empty" data-testid="quiz-topic-search-empty">
              {emptyTopics}
            </p>
          )}
        </div>
      ) : (
        <LauncherMap
          nodes={mapNodes}
          edges={mapEdges}
          courseFilter={courseFilter}
          highlightId={highlightId}
          onPick={onPick}
        />
      )}
    </section>
  );
}
