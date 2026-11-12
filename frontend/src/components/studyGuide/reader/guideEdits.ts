/**
 * The changes the reader makes to the guide it holds. Each returns a new
 * guide and leaves the one it was given alone.
 */
import type {
  Block,
  CheckAnswer,
  GuideContent,
  GuideDetail,
  MasteryChange,
  Section,
} from "@/lib/studyGuide/types";

function withSections(guide: GuideDetail, sections: Section[]): GuideDetail {
  return { ...guide, content: { ...guide.content, sections } };
}

/** The outline arrived: every section is listed, none written yet. */
export function applyOutline(guide: GuideDetail, content: GuideContent): GuideDetail {
  return { ...guide, title: content.title, content };
}

/** One section finished writing. */
export function applySection(guide: GuideDetail, written: Section): GuideDetail {
  return withSections(
    guide,
    guide.content.sections.map(section => (section.id === written.id ? written : section)),
  );
}

/** Put a regenerated block where the old one was. */
export function replaceBlock(guide: GuideDetail, blockId: string, block: Block): GuideDetail {
  return withSections(
    guide,
    guide.content.sections.map(section => ({
      ...section,
      items: section.items.map(item => (item.id === blockId ? block : item)),
    })),
  );
}

/** Mark a section read, or unread when it already was. */
export function toggleRead(readSections: string[], sectionId: string): string[] {
  return readSections.includes(sectionId)
    ? readSections.filter(id => id !== sectionId)
    : [...readSections, sectionId];
}

/** A check question was answered, and mastery may have moved with it. */
export function recordAnswer(
  guide: GuideDetail,
  blockId: string,
  answer: CheckAnswer,
  change: MasteryChange | null,
): GuideDetail {
  return {
    ...guide,
    answers: { ...guide.answers, [blockId]: answer },
    mastery: change ? { ...guide.mastery, [change.concept]: change.after } : guide.mastery,
  };
}
