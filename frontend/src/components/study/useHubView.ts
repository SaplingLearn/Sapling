"use client";
/**
 * Everything the hub's panels show for the selected course, derived from what
 * was loaded and what is selected. No fetching and no state of its own: the
 * rules live in ./studyModel.ts and ./hubModel.ts, this only decides what is
 * recomputed when.
 */
import React from "react";
import type { EnrolledCourse } from "@/lib/api";
import type { ChecklistTopic } from "@/lib/topicChecklistApi";
import {
  assessmentsForCourse,
  cardCounts,
  cardsOfCourse,
  conceptMarks,
  courseLabel,
  dueThisWeek,
  examTabs,
  prerequisitesOf,
  recentActivity,
  roadmapColumns,
  upcomingOf,
  type FlashcardRow,
} from "./hubModel";
import {
  categoriesFromChecklist,
  conceptsForCourse,
  examQueue,
  examScope,
  quickReviews,
  readiness,
  readinessBand,
} from "./studyModel";
import type { HubState } from "./useHubState";
import type { StudyGraph, StudyRecords } from "./useStudyData";

export function useHubView(input: {
  course: EnrolledCourse;
  graph: StudyGraph;
  cards: FlashcardRow[];
  records: StudyRecords;
  outline: ChecklistTopic[];
  st: HubState;
  today: Date;
}) {
  const { course, graph, cards, records, outline, st, today } = input;
  const { assignments, attempts, guides } = records;
  const cid = course.course_id;
  const label = courseLabel(course);

  // Dated work: the bell lists what is ahead, the tabs are the exams and quizzes.
  const list = React.useMemo(() => assessmentsForCourse(assignments, cid), [assignments, cid]);
  const upcoming = React.useMemo(() => upcomingOf(list, today), [list, today]);
  const { exams, exam } = React.useMemo(() => examTabs(list, today, st.exam), [list, today, st.exam]);

  // Concepts, in the outline's categories when it has some.
  const topics = React.useMemo(
    () => conceptsForCourse(graph.nodes, graph.edges, cid, today, categoriesFromChecklist(outline)),
    [graph, cid, today, outline],
  );
  const byId = React.useMemo(() => new Map(topics.map(t => [t.id, t])), [topics]);

  // What the selected exam covers. The readiness band, the roadmap and Up
  // Next all follow it; with nothing linked they are the whole course's.
  const scope = React.useMemo(() => examScope(topics, outline, exam), [topics, outline, exam]);
  const upNext = React.useMemo(() => examQueue(topics, scope), [topics, scope]);
  const marks = conceptMarks(byId, upNext.queue[0] || null, st.topic, st.hover);
  const band = React.useMemo(() => readinessBand(topics, outline, exam, label, today), [topics, outline, exam, label, today]);

  // Reviews are picked over the whole course, whichever exam is selected.
  const reviews = React.useMemo(() => quickReviews(topics, today), [topics, today]);
  const recent = React.useMemo(
    () => recentActivity({ attempts, cards, guides, topics, course, today }),
    [attempts, cards, guides, topics, course, today],
  );
  const cardCount = React.useMemo(() => cardCounts(cardsOfCourse(cards, cid)), [cards, cid]);

  return {
    label, list, upcoming, soon: dueThisWeek(upcoming, today), exams, exam,
    topics, byId, ...marks, scope,
    // The exam Up Next has run out of: its queue is the rest of the course's.
    masteredExam: upNext.fallback && scope ? scope.title : null,
    focusPrereqs: prerequisitesOf(marks.focus, byId),
    band, ready: readiness(band.concepts),
    cardCount,
    columns: roadmapColumns(topics, { ...marks, lvl: st.lvl, covered: scope?.ids }, cid, st.openCols),
    reviews,
    recent,
  };
}
