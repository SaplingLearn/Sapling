// The Learn deep links LoopLearn reads (moved out of LoopLearn.tsx unchanged).
import { readResumeParam } from "./resumeParam";

/** The Learn deep links (Dashboard, Tree, notetaker, quiz): read ONCE at mount,
 *  so a consumed `?resume=` never re-applies on a session or course switch.
 *  `note`: Send to tutor's note, whose title is `topic`. */
export type DeepLink = { resume: string | null; topic: string; course: string; mode: string; suggest: string; note: string };
export const readDeepLink = (p: { get(name: string): string | null }): DeepLink => ({
  resume: readResumeParam(p),
  topic: (p.get("topic") ?? "").trim(),
  course: (p.get("course") ?? "").trim(),
  mode: (p.get("mode") ?? "").trim(),
  suggest: (p.get("suggest") ?? "").trim(),
  note: (p.get("note") ?? "").trim(),
});
export const hasDeepLink = (d: DeepLink) => !!(d.resume || d.topic || d.course || d.mode || d.suggest || d.note);
