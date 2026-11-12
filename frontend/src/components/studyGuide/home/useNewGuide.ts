"use client";
import React from "react";

import type { EnrolledCourse } from "@/lib/api";
import { getGuideOptions } from "@/lib/studyGuide/api";
import type { Depth, Goal, GuideOptions, GuideRequest, MaterialOption, ScopeOption } from "@/lib/studyGuide/types";
import { useLatestRequest } from "@/lib/useLatestRequest";

import {
  DEFAULT_DEPTH,
  DEFAULT_GOAL,
  allIds,
  buildRequest,
  canGenerate,
  findScope,
  inListOrder,
  scopeKey,
  suggestedIds,
  toggleId,
  withNewMaterials,
  type GuideForm,
} from "./newGuideModel";

/** A class's options, under the class and term they were loaded for. */
type Loaded = { key: string; options: GuideOptions | null };

export interface NewGuide {
  course: EnrolledCourse | undefined;
  scopes: ScopeOption[];
  materials: MaterialOption[];
  /** The class's options are on their way. */
  loading: boolean;
  /** They could not be read. */
  failed: boolean;
  form: GuideForm;
  /** The choices as a request, once there is a class and a material. It keeps
   *  its identity while the choices are the same. */
  request: GuideRequest | null;
  pickCourse: (courseId: string) => void;
  pickScope: (key: string) => void;
  setGoal: (goal: Goal) => void;
  setDepth: (depth: Depth) => void;
  setUseHistory: (on: boolean) => void;
  toggleMaterial: (id: string) => void;
  pickSuggested: () => void;
  pickAll: () => void;
  pickNone: () => void;
  /** Reads the class's options again. */
  retry: () => void;
  /** After an upload: reads the materials again and selects the new ones. */
  refreshMaterials: () => Promise<void>;
}

export interface NewGuideInput {
  userId: string;
  courses: EnrolledCourse[];
  /** The active term's label, "" when no term is picked. */
  semester: string;
}

/** The New study guide dialog's choices, and the class options behind them. */
export function useNewGuide({ userId, courses, semester }: NewGuideInput): NewGuide {
  // The class picked, else the first: the form always has one to plan for.
  const [picked, setPicked] = React.useState("");
  const course = courses.find(c => c.course_id === picked) ?? courses[0];
  const courseId = course?.course_id ?? "";

  const [loaded, setLoaded] = React.useState<Loaded | null>(null);
  const [attempt, setAttempt] = React.useState(0);
  const [scopeId, setScopeId] = React.useState("");
  const [selected, setSelected] = React.useState<string[]>([]);
  const [goal, setGoal] = React.useState<Goal>(DEFAULT_GOAL);
  const [depth, setDepth] = React.useState<Depth>(DEFAULT_DEPTH);
  const [useHistory, setUseHistory] = React.useState(true);
  const req = useLatestRequest();
  const key = `${courseId}|${semester}`;

  // A class's options arrive with its first scope chosen and that scope's
  // suggested materials selected.
  React.useEffect(() => {
    if (!userId || !courseId) return;
    const run = req.begin();
    getGuideOptions(userId, courseId, semester || null)
      .then(options => {
        if (!run.isCurrent()) return;
        const first = options.scopes[0] ?? null;
        setLoaded({ key, options });
        setScopeId(first ? scopeKey(first) : "");
        setSelected(suggestedIds(first, options.materials));
      })
      .catch(err => {
        if (!run.isCurrent()) return;
        console.error("study guide options load failed", err);
        setLoaded({ key, options: null });
      });
    return req.cancel;
  }, [userId, courseId, semester, key, req, attempt]);

  // Only the options loaded for this class and term count: on a class switch
  // the form is empty until the new ones are in.
  const live = loaded?.key === key ? loaded : null;
  const scopes = React.useMemo(() => live?.options?.scopes ?? [], [live]);
  const materials = React.useMemo(() => live?.options?.materials ?? [], [live]);
  const scope = findScope(scopes, scopeId);

  const form: GuideForm = {
    courseId, semester, scope, goal, depth, useHistory,
    materialIds: inListOrder(selected, materials),
  };
  // By content, so the same choices are the same request object (usePlan
  // plans again only when it changes).
  const requestJson = canGenerate(form) ? JSON.stringify(buildRequest(form)) : "";
  const request = React.useMemo<GuideRequest | null>(
    () => (requestJson ? JSON.parse(requestJson) : null),
    [requestJson],
  );

  const refreshMaterials = async () => {
    if (!userId || !courseId) return;
    const run = req.begin();
    try {
      const next = await getGuideOptions(userId, courseId, semester || null);
      if (!run.isCurrent()) return;
      setLoaded({ key, options: next });
      setSelected(now => withNewMaterials(now, materials, next.materials));
    } catch (err) {
      // The list as it was stays; the upload itself went through.
      console.error("study guide materials refresh failed", err);
    }
  };

  return {
    course, scopes, materials, form, request,
    loading: !!courseId && live === null,
    failed: live !== null && live.options === null,
    pickCourse: setPicked,
    // A scope brings its own suggested materials.
    pickScope: next => {
      setScopeId(next);
      setSelected(suggestedIds(findScope(scopes, next), materials));
    },
    setGoal, setDepth, setUseHistory,
    toggleMaterial: id => setSelected(now => toggleId(now, id)),
    pickSuggested: () => setSelected(suggestedIds(scope, materials)),
    pickAll: () => setSelected(allIds(materials)),
    pickNone: () => setSelected([]),
    retry: () => setAttempt(n => n + 1),
    refreshMaterials,
  };
}
