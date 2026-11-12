/**
 * Onboarding's answers as one object (the draft), what each screen needs
 * before Next, and how the draft moves between screens. Stored per account
 * through lib/onboardingDraft.ts.
 */
import type { OnboardingCourse } from "@/lib/api";
import { PRIVACY_VERSION, TERMS_VERSION } from "@/lib/legal/versions";
import { readOnboardingDraft } from "@/lib/onboardingDraft";
import { LAST, SCREENS, screenIndex, type ConnChoices, type ScreenId } from "./flow";

export interface Draft {
  name: string;
  dobM: string;
  dobD: string;
  dobY: string;
  school: "" | "bu";
  year: string;
  courses: OnboardingCourse[];
  /** "My courses aren't listed": the save sends no courses. */
  coursesLater: boolean;
  termsEnd: boolean;
  termsOk: boolean;
  /** The Terms version that termsEnd and termsOk are about. */
  termsVersion: string;
  privEnd: boolean;
  privOk: boolean;
  /** The Privacy Policy version that privEnd and privOk are about. */
  privacyVersion: string;
  /** Accounts to connect once the profile is saved. */
  conn: ConnChoices;
  screen: number;
  /** Finished chapter indexes; each one grows a cluster on the graph. */
  done: number[];
}

export const EMPTY_DRAFT: Draft = {
  name: "", dobM: "", dobD: "", dobY: "", school: "", year: "", courses: [], coursesLater: false,
  termsEnd: false, termsOk: false, termsVersion: "", privEnd: false, privOk: false, privacyVersion: "",
  conn: {}, screen: 0, done: [],
};

const TERMS_SCREEN = screenIndex("terms");
const PRIVACY_SCREEN = screenIndex("privacy");

/** Whether both boxes were ticked on the Terms and Privacy Policy in force.
 * Finish sends those versions, so it needs this. */
export function legalAccepted(d: Draft): boolean {
  return d.termsOk && d.termsVersion === TERMS_VERSION && d.privOk && d.privacyVersion === PRIVACY_VERSION;
}

/**
 * Reading or accepting an older Terms or Privacy Policy (or one saved without
 * its version) doesn't count: that screen starts over, and a draft past it
 * goes back to it. So a resumed draft never sends today's version for text
 * the student never saw.
 */
export function withCurrentLegal(d: Draft): Draft {
  const terms = d.termsVersion === TERMS_VERSION ? {} : { termsEnd: false, termsOk: false, termsVersion: "" };
  const privacy = d.privacyVersion === PRIVACY_VERSION ? {} : { privEnd: false, privOk: false, privacyVersion: "" };
  const out = { ...d, ...terms, ...privacy };
  const redo = !out.termsOk ? TERMS_SCREEN : !out.privOk ? PRIVACY_SCREEN : LAST;
  return { ...out, screen: Math.min(out.screen, redo) };
}

function resumable(d: Draft): boolean {
  return Number.isInteger(d.screen) && d.screen >= 0 && d.screen <= LAST
    && Array.isArray(d.courses) && Array.isArray(d.done);
}

/** The account's saved draft, or null: none, expired, or from an older
 * onboarding shape (step/first_name), which is not resumable. Its Terms and
 * Privacy answers count only for the versions in force (withCurrentLegal). */
export function loadDraft(userId: string): Draft | null {
  const saved = readOnboardingDraft(userId);
  if (!saved) return null;
  const d = { ...EMPTY_DRAFT, ...saved } as Draft;
  return resumable(d) ? withCurrentLegal(d) : null;
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
