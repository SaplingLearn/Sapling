"use client";

/**
 * Quiz home's right column: "Choose a topic" — the course pills and the
 * search over every concept on the tree (`TopicList`).
 */

import React from "react";
import { Icon } from "@/components/Icon";
import { Pill } from "@/components/Pill";
import { colorFor } from "@/lib/quiz/proposals";
import type { QuizHome as QuizHomeData } from "@/lib/quiz/useQuizHome";
import { TopicList, type TopicListProps } from "./TopicList";

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
              style={{ background: colorFor(nodes[0], course) }}
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
}: TopicsColumnProps) {
  return (
    <section className="quiz-home__topics-col" aria-label="Choose a topic">
      {/* One row of controls over the list: the course pills on the left (only
          when there is more than one course to choose between), the search on
          the right, centred on one line. */}
      <div className="quiz-home__toolbar">
        {byCourse.length > 1 && (
          <CoursePills byCourse={byCourse} courseFilter={courseFilter} onCourse={onCourse} />
        )}
        <TopicSearch topicQuery={topicQuery} onQuery={onQuery} />
      </div>
      {/* Capped to the proposal's height and scrolled inside (`home.css`). */}
      <div className="quiz-home__topics-scroll">
        {topicGroups.length > 0 ? (
          <TopicList
            groups={topicGroups}
            onPick={onPick}
            onIntent={onIntent}
            returnedId={returnedId}
          />
        ) : (
          <p className="quiz-home__topics-empty" data-testid="quiz-topic-search-empty">
            {emptyTopics}
          </p>
        )}
      </div>
    </section>
  );
}
