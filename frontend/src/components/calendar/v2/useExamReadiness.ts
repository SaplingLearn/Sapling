"use client";
// How ready the student is for each upcoming exam on the calendar, by the
// Tutor's milestone rules (learn/tutor/milestones.ts): an exam covers the
// concepts its course's topic outline links to it, and a concept is ready at
// Proficient. One graph read and one outline read per course that has an
// exam. Only with `milestones` on (a loop flag: off whenever the loop is).
import { useEffect, useMemo, useState } from "react";
import { getGraph, type EnrolledCourse } from "@/lib/api";
import { apiToGraphNode, type GraphNode } from "@/lib/data";
import type { GraphNode as ApiNode } from "@/lib/types";
import { getTopicChecklist } from "@/lib/topicChecklistApi";
import { useUser } from "@/context/UserContext";
import { conceptIdsForExam } from "../../study/studyModel";
import { coveredConcepts, readinessOf, type ConceptState } from "../../learn/tutor/milestones";
import type { CalItem } from "./calendarModel";

export interface ExamReadiness {
  concepts: ConceptState[];
  ready: number;
  total: number;
}

type Outline = Parameters<typeof conceptIdsForExam>[0];

export function useExamReadiness(exams: readonly CalItem[], courses: readonly EnrolledCourse[], enabled: boolean) {
  const { userId } = useUser();
  const courseKey = [...new Set(exams.map((e) => e.courseId).filter((c): c is string => !!c))].sort().join(",");
  const [nodes, setNodes] = useState<GraphNode[] | null>(null);
  const [outlines, setOutlines] = useState<Map<string, Outline>>(new Map());

  useEffect(() => {
    if (!enabled || !userId || !courseKey) return;
    let live = true;
    getGraph(userId)
      .then((g) => { if (live) setNodes(((g.nodes ?? []) as ApiNode[]).map((n) => apiToGraphNode(n, [...courses]))); })
      .catch(() => { if (live) setNodes([]); });
    Promise.all(courseKey.split(",").map((cid) => getTopicChecklist(userId, cid)
      .then((r) => [cid, r.topics ?? []] as const)
      .catch(() => [cid, [] as Outline] as const)))
      .then((pairs) => { if (live) setOutlines(new Map(pairs)); });
    return () => { live = false; };
    // courses only names the nodes' colours; re-reading on a new array would loop
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, userId, courseKey]);

  return useMemo(() => {
    const out = new Map<string, ExamReadiness>();
    if (!enabled || !nodes) return out;
    for (const e of exams) {
      const outline = e.courseId ? outlines.get(e.courseId) : undefined;
      if (!outline) continue;
      const concepts = coveredConcepts([...conceptIdsForExam(outline, e.id)], nodes);
      if (concepts.length === 0) continue;
      const { ready, total } = readinessOf(concepts);
      out.set(e.id, { concepts, ready, total });
    }
    return out;
  }, [enabled, nodes, outlines, exams]);
}
