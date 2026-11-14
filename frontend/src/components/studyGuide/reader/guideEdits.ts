/**
 * The changes the reader makes to the guide it holds. Each returns a new
 * guide and leaves the one it was given alone.
 */
import type {
  AnswerResult,
  Block,
  CheckAnswer,
  GuideContent,
  GuideDetail,
  Section,
} from "@/lib/studyGuide/types";

function withSections(guide: GuideDetail, sections: Section[]): GuideDetail {
  return { ...guide, content: { ...guide.content, sections } };
}

/**
 * The outline arrived: every section is listed, and only the ones an Update
 * keeps are written. Read marks and check answers stay with those sections
 * alone, as on the server: every other section is new, under an id the guide
 * has not used before, and the sections the old marks were on are gone.
 */
export function applyOutline(guide: GuideDetail, content: GuideContent): GuideDetail {
  const kept = content.sections.filter(section => section.status === "written");
  const sectionIds = new Set(kept.map(section => section.id));
  const itemIds = new Set(kept.flatMap(section => section.items.map(item => item.id)));
  const answers: Record<string, CheckAnswer> = {};
  for (const [blockId, answer] of Object.entries(guide.answers)) {
    if (itemIds.has(blockId)) answers[blockId] = answer;
  }
  return {
    ...guide,
    title: content.title,
    content,
    read_sections: guide.read_sections.filter(id => sectionIds.has(id)),
    answers,
  };
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

/**
 * A check question was answered. The guide then holds what the server would
 * send for it on the next load: the answer, the question's correct option and
 * the explanation for this pick, and the mastery the answer may have moved.
 *
 * The server keeps only the first answer, so a later pick comes back
 * uncounted and the guide keeps the first one it holds. Only when it holds
 * none (another tab answered first) is the uncounted pick shown, as the
 * nearest thing to what the server has.
 */
export function recordAnswer(
  guide: GuideDetail,
  blockId: string,
  optionId: string,
  result: AnswerResult,
): GuideDetail {
  if (!result.counted && guide.answers[blockId]) return guide;
  const explained = result.correct
    ? { explain_correct: result.explanation }
    : { explain_incorrect: result.explanation };
  const sections = guide.content.sections.map(section => ({
    ...section,
    items: section.items.map(item =>
      item.id === blockId && item.type === "check"
        ? { ...item, correct_id: result.correct_id, ...explained }
        : item,
    ),
  }));
  const change = result.mastery;
  return {
    ...withSections(guide, sections),
    answers: { ...guide.answers, [blockId]: { option_id: optionId, correct: result.correct } },
    mastery: change ? { ...guide.mastery, [change.concept]: change.after } : guide.mastery,
  };
}
