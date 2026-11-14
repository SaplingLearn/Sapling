/**
 * Onboarding's answers as one object (the draft), what each screen needs
 * before Next, and how the draft moves between screens. Stored per account
 * through lib/onboardingDraft.ts.
 */
import type { OnboardingCourse } from "@/lib/api";
import { readOnboardingDraft } from "@/lib/onboardingDraft";
import { LAST, SCREENS, screenIndex, type ConnChoices, type ScreenId } from "./flow";

export interface Draft {
  /** The first name to call the student by. */
  name: string;
  /** Optional; prefilled from the Google account like the first name. */
  lastName: string;
  dobM: string;
  dobD: string;
  dobY: string;
  school: "" | "bu";
  year: string;
  courses: OnboardingCourse[];
  /** "My courses aren't listed": the save sends no courses. */
  coursesLater: boolean;
  /** The Terms and Privacy answers live only as long as the page: they are
   * never stored (forStorage), so they always belong to the text this page
   * shows, which is the version Finish sends. */
  termsEnd: boolean;
  termsOk: boolean;
  privEnd: boolean;
  privOk: boolean;
  /** Accounts to connect once the profile is saved. */
  conn: ConnChoices;
  screen: number;
  /** Finished chapter indexes; each one grows a cluster on the graph. */
  done: number[];
}

export const EMPTY_DRAFT: Draft = {
  name: "", lastName: "", dobM: "", dobD: "", dobY: "", school: "", year: "", courses: [], coursesLater: false,
  termsEnd: false, termsOk: false, privEnd: false, privOk: false,
  conn: {}, screen: 0, done: [],
};

const TERMS_SCREEN = screenIndex("terms");
const NOT_AGREED = { termsEnd: false, termsOk: false, privEnd: false, privOk: false } as const;

/** What is written to storage: the draft without its Terms and Privacy answers. */
export function forStorage(d: Draft): Draft {
  return { ...d, ...NOT_AGREED };
}

function resumable(d: Draft): boolean {
  return Number.isInteger(d.screen) && d.screen >= 0 && d.screen <= LAST
    && Array.isArray(d.courses) && Array.isArray(d.done);
}

/** The account's saved draft, or null: none, expired, or from an older
 * onboarding shape (step/first_name), which is not resumable. The Terms and
 * Privacy are agreed to again on every visit, so a draft saved past them
 * resumes at the Terms (and one saved with answers, before they stopped being
 * stored, has them dropped). */
export function loadDraft(userId: string): Draft | null {
  const saved = readOnboardingDraft(userId);
  if (!saved) return null;
  const d = { ...EMPTY_DRAFT, ...saved, ...NOT_AGREED } as Draft & Record<string, unknown>;
  // The versions older drafts kept beside those answers.
  delete d.termsVersion;
  delete d.privacyVersion;
  return resumable(d) ? { ...d, screen: Math.min(d.screen, TERMS_SCREEN) } : null;
}

/** Whether the screen's answers let the student move on. */
export function canAdvance(id: ScreenId, d: Draft, age: number | null, blocked: boolean): boolean {
  switch (id) {
    case "name": return d.name.trim().length > 0;
    case "birthday": return !blocked && age !== null && age >= 13;
    case "school": return d.school === "bu";
    case "courses": return !!d.year && (d.courses.length > 0 || d.coursesLater);
    case "terms": return d.termsOk;
    case "privacy": return d.privOk;
    default: return true;
  }
}

function withChapter(done: number[], ch: number): number[] {
  return done.includes(ch) ? done : [...done, ch];
}

/** The next screen; leaving a chapter marks it finished. */
export function advance(d: Draft): Draft {
  const ni = Math.min(d.screen + 1, LAST);
  const ch = SCREENS[d.screen].ch;
  return { ...d, screen: ni, done: SCREENS[ni].ch !== ch ? withChapter(d.done, ch) : d.done };
}

/** Finishing marks the last chapter done too (the graph grows its cluster). */
export function finished(d: Draft): Draft {
  return { ...d, done: withChapter(d.done, SCREENS[d.screen].ch) };
}
