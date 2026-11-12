/**
 * What the reader shows, derived from a guide. Pure: no React, no network.
 */
import type {
  Depth,
  Goal,
  GuideContent,
  GuideDetail,
  Section,
  SectionBar,
  Source,
  Tier,
} from "@/lib/studyGuide/types";

export type ViewMode = "read" | "skim";

export const GOAL_LABEL: Record<Goal, string> = {
  practice: "Practice",
  review: "Review",
  exam_prep: "Exam prep",
};

export const DEPTH_LABEL: Record<Depth, string> = {
  cram: "Cram sheet",
  standard: "Standard",
  deep: "Deep review",
};

export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The id a section is anchored and tested under. */
export const sectionAnchor = (sectionId: string) => `guide-section-${sectionId}`;
export const SOURCES_ANCHOR = "guide-sources";

/** "01", "02", ... */
export const sectionNumber = (index: number) => String(index + 1).padStart(2, "0");

const DAY_MS = 86_400_000;

/** A `YYYY-MM-DD` (or ISO) date as UTC midnight, or null when it is not one. */
function dayOf(date: string | null): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(date ?? "");
  if (!match) return null;
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

/** Whole days from today to the due date. Null with no date, or one that has passed. */
export function daysUntil(dueDate: string | null, now: Date): number | null {
  const due = dayOf(dueDate);
  if (due === null) return null;
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((due - today) / DAY_MS);
  return days < 0 ? null : days;
}

/** "Midterm 2 in 6 days". */
export function countdownLabel(scopeLabel: string, days: number): string {
  return days === 0 ? `${scopeLabel} is today` : `${scopeLabel} in ${plural(days, "day")}`;
}

/** "6 days left". */
export const daysLeftLabel = (days: number) => (days === 0 ? "Today" : `${plural(days, "day")} left`);

/** "Wed, Nov 18", or "" when there is no date. */
export function dueDateLabel(dueDate: string | null): string {
  const due = dayOf(dueDate);
  if (due === null) return "";
  return new Date(due).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** "6 sources · about 14 min". The time is left off until the guide has one. */
export function sourcesLabel(sources: number, minutes: number): string {
  const count = plural(sources, "source");
  return minutes > 0 ? `${count} · about ${minutes} min` : count;
}

/** "2 new lectures since this guide was made". */
export const staleLabel = (count: number) => `${plural(count, "new lecture")} since this guide was made`;

/** The space bar, read off the sections so it fills in with the outline. */
export function sectionBars(content: GuideContent): SectionBar[] {
  return content.sections.map(({ title, tier, weight }) => ({ title, tier, weight }));
}

/** How many of the guide's sections are marked read. */
export function readCount(guide: GuideDetail): number {
  return guide.content.sections.filter(section => guide.read_sections.includes(section.id)).length;
}

/** "2 of 4 sections read", or "Guide finished". */
export function progressTitle(read: number, total: number): string {
  return total > 0 && read === total ? "Guide finished" : `${read} of ${plural(total, "section")} read`;
}

/** A section's mastery now, falling back to what it was when written. */
export function liveTier(section: Section, mastery: Record<string, Tier>): Tier {
  return (section.concept && mastery[section.concept]) || section.tier;
}

/** A concept's mastery now. One the tree does not have yet is Not Started. */
export const conceptTier = (concept: string, mastery: Record<string, Tier>): Tier =>
  mastery[concept] ?? "unexplored";

/** The source a citation points at, or null when the guide does not list it. */
export const findSource = (sources: Source[], id: string | null): Source | null =>
  sources.find(source => source.id === id) ?? null;

export type SectionPhase = "written" | "writing" | "queued" | "failed";

/**
 * Where each section stands. While the guide is being written the first
 * queued section is the one in progress.
 */
export function sectionPhases(sections: Section[], generating: boolean): Record<string, SectionPhase> {
  const phases: Record<string, SectionPhase> = {};
  let writing = generating;
  for (const section of sections) {
    if (section.status !== "queued") {
      phases[section.id] = section.status;
    } else {
      phases[section.id] = writing ? "writing" : "queued";
      writing = false;
    }
  }
  return phases;
}

export const PHASE_LABEL: Record<SectionPhase, string> = {
  written: "Written",
  writing: "Writing",
  queued: "Queued",
  failed: "Not written",
};

/** What the tutor is told about the guide a question comes from. */
export function tutorQuestion(guide: GuideDetail, question: string): string {
  const outline = guide.content.sections
    .map((section, i) => `${i + 1}. ${section.title}${section.one_line ? `: ${section.one_line}` : ""}`)
    .join("\n");
  return [
    `I am reading my study guide "${guide.content.title}" for ${guide.course_name}.`,
    outline && `Its sections:\n${outline}`,
    `My question: ${question}`,
  ]
    .filter(Boolean)
    .join("\n\n");
}
