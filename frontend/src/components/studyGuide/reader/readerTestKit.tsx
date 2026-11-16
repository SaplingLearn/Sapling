/**
 * Shared by the reader's DOM tests: shapes built from the contract fixture
 * and a render helper.
 *
 * Each test file mocks `@/lib/studyGuide/api`, `@/context/UserContext`,
 * `next/navigation`, `next/dynamic` and the markdown renderer itself (mocks
 * are per file); this module only holds what does not need hoisting.
 */
import { render } from "@testing-library/react";

import { ToastProvider } from "@/components/ToastProvider";
import type { GuideContent, GuideDetail, Section } from "@/lib/studyGuide/types";

import { GuideReader } from "./GuideReader";

export { fixtureGuide } from "./readerFixture";

export const USER_ID = "u1";
/** Six days before the fixture's due date (2026-03-17). */
export const NOW = new Date(2026, 2, 11, 9, 0, 0);

export function sectionOf(guide: GuideDetail, id: string): Section {
  const section = guide.content.sections.find(candidate => candidate.id === id);
  if (!section) throw new Error(`fixture has no section ${id}`);
  return section;
}

/** The fixture as its outline: every section listed, none written. */
export function outlineOf(guide: GuideDetail): GuideContent {
  return {
    ...guide.content,
    sections: guide.content.sections.map(section => ({ ...section, status: "queued", items: [] })),
  };
}

/** A guide whose row exists but has no outline yet. */
export function newGuide(guide: GuideDetail): GuideDetail {
  return {
    ...guide,
    status: "generating",
    generated_at: null,
    new_materials: 0,
    read_sections: [],
    content: { ...guide.content, deck: "", takeaways: [], sections: [], sources: [] },
  };
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

export function renderReader(guideId = "guide-fixture-1") {
  return render(
    <ToastProvider>
      <GuideReader guideId={guideId} now={NOW} />
    </ToastProvider>,
  );
}
