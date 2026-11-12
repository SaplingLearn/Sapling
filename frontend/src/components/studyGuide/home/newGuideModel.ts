/**
 * The New study guide dialog's rules, as pure functions: the defaults, which
 * materials a scope pre-selects, the selection cap, and the request the
 * choices become.
 */
import type {
  Depth,
  Goal,
  GuideRequest,
  MaterialOption,
  ScopeOption,
} from "@/lib/studyGuide/types";

import { dueDateText } from "../shared/dates";
import { DEPTH_LABEL, GOAL_LABEL } from "../shared/labels";

/** The most materials one guide is written from (the request's own limit). */
export const MAX_MATERIALS = 30;

export const DEFAULT_GOAL: Goal = "exam_prep";
export const DEFAULT_DEPTH: Depth = "standard";

export const GOAL_OPTIONS: { value: Goal; label: string }[] = (
  ["practice", "review", "exam_prep"] as const
).map(value => ({ value, label: GOAL_LABEL[value] }));

export const DEPTH_OPTIONS: { value: Depth; label: string }[] = (
  ["cram", "standard", "deep"] as const
).map(value => ({ value, label: DEPTH_LABEL[value] }));

/** A scope as one string: "course", or "exam:<id>" / "assignment:<id>". */
export const scopeKey = (scope: Pick<ScopeOption, "kind" | "id">): string =>
  scope.id ? `${scope.kind}:${scope.id}` : scope.kind;

export const findScope = (scopes: ScopeOption[], key: string): ScopeOption | null =>
  scopes.find(scope => scopeKey(scope) === key) ?? null;

const KIND_LABEL: Record<ScopeOption["kind"], string> = {
  course: "Whole course",
  exam: "Exam",
  assignment: "Assignment",
};

/** The line under a scope's title: what it is, and when it is due. */
export function scopeNote(scope: ScopeOption): string {
  const due = dueDateText(scope.due_date);
  return due ? `${KIND_LABEL[scope.kind]} · due ${due}` : KIND_LABEL[scope.kind];
}

const capped = (ids: string[]): string[] => ids.slice(0, MAX_MATERIALS);

/** The scope's suggested materials that the class still has, up to the cap. */
export function suggestedIds(scope: ScopeOption | null, materials: MaterialOption[]): string[] {
  const suggested = new Set(scope?.suggested_material_ids ?? []);
  return capped(materials.filter(material => suggested.has(material.id)).map(material => material.id));
}

/** Every material, up to the cap. */
export const allIds = (materials: MaterialOption[]): string[] =>
  capped(materials.map(material => material.id));

export const atCap = (selected: string[]): boolean => selected.length >= MAX_MATERIALS;

/** One tile pressed. At the cap a tile can still be turned off, not on. */
export function toggleId(selected: string[], id: string): string[] {
  if (selected.includes(id)) return selected.filter(other => other !== id);
  return atCap(selected) ? selected : [...selected, id];
}

/** The selection plus the materials that were not there before (an upload). */
export function withNewMaterials(selected: string[], before: MaterialOption[], after: MaterialOption[]): string[] {
  const known = new Set(before.map(material => material.id));
  const kept = selected.filter(id => after.some(material => material.id === id));
  const added = after.filter(material => !known.has(material.id) && !kept.includes(material.id));
  return capped([...kept, ...added.map(material => material.id)]);
}

/** The picked ids in the order the class lists its materials. */
export const inListOrder = (selected: string[], materials: MaterialOption[]): string[] =>
  materials.filter(material => selected.includes(material.id)).map(material => material.id);

export interface GuideForm {
  courseId: string;
  /** The active term's label, "" when no term is picked. */
  semester: string;
  scope: ScopeOption | null;
  goal: Goal;
  depth: Depth;
  /** In the class's own order (`inListOrder`), so one choice is one request. */
  materialIds: string[];
  useHistory: boolean;
}

/** A guide needs a class and at least one material. */
export const canGenerate = (form: GuideForm): boolean =>
  !!form.courseId && form.materialIds.length > 0;

/** The choices as the request the plan and create calls take. */
export function buildRequest(form: GuideForm): GuideRequest {
  return {
    course_id: form.courseId,
    semester: form.semester || null,
    scope_kind: form.scope?.kind ?? "course",
    scope_id: form.scope?.id ?? null,
    goal: form.goal,
    depth: form.depth,
    material_ids: form.materialIds,
    use_history: form.useHistory,
  };
}
