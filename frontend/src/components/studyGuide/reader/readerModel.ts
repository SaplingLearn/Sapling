/**
 * What the reader shows, derived from a guide. Pure: no React, no network.
 */
import { dueDay } from "@/components/studyGuide/shared/dates";
import { newLecturesText, plural } from "@/components/studyGuide/shared/labels";
import type {
  GuideContent,
  GuideDetail,
  Section,
  SectionBar,
  Source,
  Tier,
} from "@/lib/studyGuide/types";

export type ViewMode = "read" | "skim";

/** The id a section is anchored and tested under. */
export const sectionAnchor = (sectionId: string) => `guide-section-${sectionId}`;
export const SOURCES_ANCHOR = "guide-sources";

/** "01", "02", ... */
export const sectionNumber = (index: number) => String(index + 1).padStart(2, "0");

const DAY_MS = 86_400_000;

/** Whole days from today to the due date. Null with no date, or one that has passed. */
export function daysUntil(dueDate: string | null, now: Date): number | null {
  const due = dueDay(dueDate);
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

/** "6 sources · about 14 min". The time is left off until the guide has one. */
export function sourcesLabel(sources: number, minutes: number): string {
  const count = plural(sources, "source");
  return minutes > 0 ? `${count} · about ${minutes} min` : count;
}

/** "2 new lectures since this guide was made". */
export const staleLabel = (count: number) => `${newLecturesText(count)} since this guide was made`;

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

/** A line that opens a block: a code fence, display math, a list item, a heading, a quote, a table row. */
const BLOCK_START = /^ {0,3}(```|~~~|\$\$|[-*+] |\d+[.)] |#{1,6} |>|\|)/m;

/**
 * Whether a paragraph's Markdown is more than one run of text: a fenced code
 * block, a list (the upgraded old guides' `- a\n- b`), or several blocks.
 */
export function isBlockMarkdown(text: string): boolean {
  const body = text.trim();
  return BLOCK_START.test(body) || /\n\s*\n/.test(body);
}

export type SectionPhase = "written" | "writing" | "queued" | "failed";

/**
 * Where each section stands. A generation writes the sections that are not
 * written in order, failed ones included, so while one runs the first of
 * them is the one in progress and the rest wait. `tried` names the sections
 * this run is already done with: one of those that failed stays failed.
 */
export function sectionPhases(
  sections: Section[],
  generating: boolean,
  tried: readonly string[],
): Record<string, SectionPhase> {
  const phases: Record<string, SectionPhase> = {};
  let writing = generating;
  for (const section of sections) {
    const waits = generating && section.status !== "written" && !tried.includes(section.id);
    if (!waits) {
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
