import type { OnboardingCourse } from "@/lib/api";

export const ONBOARDING_VERSION = 3;
export const YEARS = ["freshman", "sophomore", "junior", "senior", "graduate", "other"] as const;
export type OnboardingStep = 0 | 1 | 2 | 3 | 4 | 5;
export interface SavedMaterial { id: string; name: string; courseId: string; size?: number }
export interface OnboardingDraft {
  version: 3;
  userId: string;
  firstName: string;
  lastName: string;
  year: string;
  majorsText: string;
  minorsText: string;
  courseIds: string[];
  courseCache: OnboardingCourse[];
  step: OnboardingStep;
  requiredSaved: boolean;
  goalCourseId: string;
  goalScope: "course" | "concepts";
  goalTargets: string[];
  objective: string;
  materials: SavedMaterial[];
  handoffId?: string;
}

export const onboardingDraftKey = (userId: string) => `sapling_onboarding_v${ONBOARDING_VERSION}:${userId}`;
export const academicChoices = (text: string) => [...new Set(text.split(",").map(value => value.trim()).filter(Boolean))];

export function emptyOnboardingDraft(userId: string, name = ""): OnboardingDraft {
  const [firstName = "", ...last] = name.trim().split(/\s+/);
  return { version: 3, userId, firstName, lastName: last.join(" "), year: "", majorsText: "", minorsText: "", courseIds: [], courseCache: [], step: 0, requiredSaved: false, goalCourseId: "", goalScope: "course", goalTargets: [], objective: "", materials: [] };
}

function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === "string");
}

/** Old unscoped drafts cannot be associated with an authenticated account safely. */
export function readOnboardingDraft(userId: string): OnboardingDraft | null {
  try {
    const raw = localStorage.getItem(onboardingDraftKey(userId));
    if (!raw) return null;
    const d = JSON.parse(raw) as Partial<OnboardingDraft>;
    if (d.version !== 3 || d.userId !== userId || !Number.isInteger(d.step) || d.step! < 0 || d.step! > 5) return null;
    if (![d.firstName, d.lastName, d.year, d.majorsText, d.minorsText, d.goalCourseId, d.objective].every(value => typeof value === "string")) return null;
    if (d.year && !YEARS.includes(d.year as typeof YEARS[number])) return null;
    if (!strings(d.courseIds) || !strings(d.goalTargets) || d.goalTargets.length > 12 || d.objective!.length > 500 || typeof d.requiredSaved !== "boolean") return null;
    if (!Array.isArray(d.courseCache) || !d.courseCache.every(c => c && typeof c.id === "string" && typeof c.course_code === "string" && typeof c.course_name === "string")) return null;
    if (!Array.isArray(d.materials) || !d.materials.every(m => m && typeof m.id === "string" && typeof m.name === "string" && typeof m.courseId === "string")) return null;
    if (d.goalScope !== "course" && d.goalScope !== "concepts") return null;
    // A corrupt checkpoint cannot bypass required profile/course submission.
    if (d.step! > 2 && !d.requiredSaved) d.step = 2;
    return d as OnboardingDraft;
  } catch { return null; }
}

export function writeOnboardingDraft(draft: OnboardingDraft): boolean {
  try { localStorage.setItem(onboardingDraftKey(draft.userId), JSON.stringify(draft)); return true; }
  catch { return false; }
}

export function canContinueOnboarding(draft: OnboardingDraft): boolean {
  switch (draft.step) {
    case 0: return Boolean(draft.firstName.trim() && draft.lastName.trim());
    case 1: return YEARS.includes(draft.year as typeof YEARS[number]) && academicChoices(draft.majorsText).length > 0;
    case 2: return draft.courseIds.length > 0;
    case 3: return draft.requiredSaved;
    case 4: return Boolean(draft.goalCourseId) && (draft.goalScope === "course" || (draft.goalTargets.length >= 1 && draft.goalTargets.length <= 12));
    case 5: return draft.requiredSaved && Boolean(draft.goalCourseId);
  }
}
