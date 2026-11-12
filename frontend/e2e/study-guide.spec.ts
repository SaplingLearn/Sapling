/**
 * Journeys: study guides, from the home to a written guide and back
 * (the study-guide redesign, docs/design/study-guide-redesign.md).
 *
 *   the acceptance journey   home, the New study guide dialog, the reader
 *                            writing the guide, Skim, a check-yourself answer
 *                            that moves mastery once, a read mark, Save to
 *                            Library, the saved card on the home and in the
 *                            Library.
 *   one block, regenerated   only that block changes, under the same id.
 *   the seeded guide         a stored guide opens whole, with no generation.
 *   a reload                 the guide and what the student did on it come back.
 *
 * LLM-dependence. A guide is written by three agents on the `study_guide`
 * task (outline, section writer, block rewriter), so the stack must be the
 * deterministic lane:
 *
 *   SAPLING_MODEL_MODE=function \
 *   SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e make e2e-up
 *
 * (a cycle from scripts/e2e-cycle.sh defaults to it). One handler in
 * backend/agents/function_handlers_e2e.py answers all three with fixed
 * constants; every literal under "The scripted guide" below is a transcription
 * of them, and backend/tests/test_e2e_function_handlers.py pins the Python
 * side. KEEP THE THREE IN SYNC. The generating journeys fail fast on
 * /api/health's `model_mode` before anything is written.
 *
 * Which class. The scripted outline teaches three concepts the rich seed puts
 * in rich-user-active's CS101 tree, so the guide has to be a CS101 guide for
 * mastery to join. That student holds CS101 in two terms and only the Fall
 * 2025 offering has documents (db/seed_local_rich.py). Under the default "All
 * semesters" the server resolves CS101 to the student's latest offering,
 * Spring 2026, which has none, and the dialog cannot generate. So the dialog
 * journey runs with Fall 2025 picked, and the API-created guides name it.
 *
 * The generation budget. A student may start 20 generations and 40 block
 * rewrites an hour (services/study_guides/limits.py), and the limiter is per
 * backend process, so the per-test reset does not clear it. The E2E stack
 * raises all three study-guide limits (scripts/e2e-up.sh), as it does the
 * quiz limit, so repeated runs on a held stack do not run out.
 *
 * Waiting is event-based only: auto-retrying expects and `expect.poll` on a
 * row, never a sleep.
 */
import type { APIRequestContext, Page } from "@playwright/test";

import type { GuideContent, GuideOptions, Item } from "@/lib/studyGuide/types";

import { queryRaw } from "./support/db";
import { decryptText } from "./support/decrypt";
import { expect, test } from "./support/fixtures";
import {
  COURSE_ID_CS,
  MASTERY_PER_CORRECT,
  MASTERY_PER_WRONG,
  NODE_ID,
  masteryOf,
} from "./support/quiz";
import { BACKEND_URL, USER_ACTIVE } from "./support/stack";

// ── The rich seed (db/seed_local_rich.py) ──────────────────────────────────

/** The one seeded guide: ready, not saved, nothing read or answered. */
const SEEDED_GUIDE = {
  id: "rich-guide-cs-f25-mid",
  title: "Variables, control flow and functions",
  madeAt: "2026-03-01T12:00:00Z",
};
const COURSE_NAME_CS = "Introduction to Computer Science";
const COURSE_ID_MATH = "rich-course-math210";
/** The term label of the only CS101 offering that has documents. */
const TERM = "Fall 2025";
const OFFERING_CS_F25 = "rich-off-cs101-f25";
/** Two seeded rows are titled "Midterm Exam". This one is CS101 Fall 2025's. */
const EXAM_CS_F25 = "rich-asg-cs-f25-mid";
/** The other one, MATH210 Spring 2026's: never a CS101 scope. */
const EXAM_MATH_S26 = "rich-asg-math-s26-mid";
const SYLLABUS_DOC = "rich-doc-cs-syllabus";

// ── The scripted guide (backend/agents/function_handlers_e2e.py) ────────────

/** `E2E_STUDY_GUIDE_OUTLINE`. The server sets each section's id, tier and
 *  share: the concepts are struggling, learning and mastered for the seeded
 *  student, which weigh 5, 3 and 1 (services/study_guides/plan.py). */
const GUIDE_TITLE = "Recursion and what it builds on";
const TAKEAWAY = "Every recursive function needs a base case so it can stop calling itself.";
const SECTIONS = [
  { id: "s1", title: "Recursion", tier: "Struggling", share: 56 },
  { id: "s2", title: "Control flow", tier: "Learning", share: 33 },
  { id: "s3", title: "Variables and types", tier: "Mastered", share: 11 },
] as const;

/**
 * `E2E_STUDY_GUIDE_SECTION_TEXT`, the body of every section. Item ids are
 * `{sectionId}-i{n}`, n being the item's place (services/study_guides/markup.py):
 *
 *   i1 prose, two paragraphs, cites S1, has a Skim summary
 *   i2 formula
 *   i3 worked_example
 *   i4 prose, one paragraph, no summary
 *   i5 comparison
 *   i6 key_terms
 *   i7 concept_map
 *   i8 check (options a, b, c; correct b; concept Recursion)
 */
const PLACE = {
  prose: 1,
  formula: 2,
  workedExample: 3,
  proseNoSummary: 4,
  comparison: 5,
  keyTerms: 6,
  conceptMap: 7,
  check: 8,
} as const;
const BLOCK_PLACES = [
  PLACE.formula,
  PLACE.workedExample,
  PLACE.comparison,
  PLACE.keyTerms,
  PLACE.conceptMap,
  PLACE.check,
];
const itemId = (sectionId: string, place: number) => `${sectionId}-i${place}`;

/** The first passage's first paragraph, as rendered: `**base case**` is a
 *  highlighted term and `[S1]` has become a source chip. */
const PROSE_SNIPPET = "Every one needs a base case: an input it answers directly, without another call.";
const SKIM_SUMMARY =
  "A recursive function calls itself on a smaller input until it reaches " +
  "a base case it can answer directly.";
const UNSUMMARISED_SNIPPET = "On an exam you are usually asked to trace the calls";
const KEY_TERMS = { title: "New in this section", onlyTerm: "Recursive step" };
/** `E2E_STUDY_GUIDE_BLOCK_TEXT`: the reply to every block rewrite. */
const REWRITTEN_KEY_TERMS = { title: "Key terms, rewritten", onlyTerm: "Stack overflow" };
/** The check's explanations as stored: the server capitalises the first
 *  letter (services/study_guides/verify.py::_without_verdict). */
const CHECK = {
  wrong: "a",
  right: "b",
  explainIncorrect: "Write one line per call until you reach the base case, then multiply back up.",
  explainCorrect:
    "Factorial(3) is 3 times factorial(2), which is 2 times factorial(1), which is 1. That makes 6.",
} as const;

/** `services/study_guides/answers.py`: the event a first answer journals. */
const EVENT_CORRECT = "guide_check_correct";
const EVENT_INCORRECT = "guide_check_incorrect";

/** Generous for three scripted sections; it normally takes a second or two. */
const GENERATION_TIMEOUT = 60_000;
const LOAD_TIMEOUT = 20_000;

const THREE_SECTIONS_HINT =
  "The scripted outline (E2E_STUDY_GUIDE_OUTLINE) has three sections and a cram guide may " +
  "have up to three (services/study_guides/outline.py::section_range).";

// ── Helpers ────────────────────────────────────────────────────────────────

/** Never write a guide on a real-mode stack: it would call the live model. */
async function requireFunctionMode(): Promise<void> {
  const health = (await (await fetch(`${BACKEND_URL}/api/health`)).json()) as {
    model_mode?: string;
  };
  expect(
    health.model_mode,
    "Stack is not in deterministic model mode. Reboot it with:\n" +
      "  SAPLING_MODEL_MODE=function " +
      "SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e make e2e-up",
  ).toBe("function");
}

type StoredGuide = {
  user_id: string;
  offering_id: string;
  exam_id: string | null;
  scope_kind: string;
  goal: string;
  depth: string;
  use_history: boolean;
  status: string;
  format: number;
  material_ids: string[];
  read_sections: string[];
  saved_at: Date | null;
  generating_at: Date | null;
  generated_at: Date | null;
  content_type: string | null;
  content_cipher: string | null;
  answers_type: string | null;
  answers_cipher: string | null;
};

/** One `study_guides` row. The two encrypted columns come back as stored: a
 *  JSON string of ciphertext (`#>> '{}'` unwraps the string). */
async function storedGuide(guideId: string): Promise<StoredGuide> {
  const rows = await queryRaw(
    `SELECT user_id, offering_id, exam_id, scope_kind, goal, depth, use_history,
            status, format, material_ids, read_sections, saved_at,
            generating_at, generated_at,
            jsonb_typeof(content) AS content_type, content #>> '{}' AS content_cipher,
            jsonb_typeof(answers) AS answers_type, answers #>> '{}' AS answers_cipher
       FROM study_guides
      WHERE id = $1`,
    [guideId],
  );
  expect(rows, `study_guides row ${guideId}`).toHaveLength(1);
  return rows[0] as StoredGuide;
}

/** The stored content, decrypted by the backend's own helper. */
async function storedContent(guideId: string): Promise<GuideContent> {
  const { content_cipher } = await storedGuide(guideId);
  return JSON.parse(await decryptText(content_cipher ?? "")) as GuideContent;
}

const itemsOf = (content: GuideContent): Item[] => content.sections.flatMap(section => section.items);

/** The student's documents in CS101 Fall 2025, in the order the server labels
 *  them S1, S2, ... (services/study_guides/materials.py). */
async function classDocuments(): Promise<{ id: string; file_name: string }[]> {
  const rows = await queryRaw(
    `SELECT id, file_name
       FROM documents
      WHERE user_id = $1 AND offering_id = $2 AND deleted_at IS NULL
      ORDER BY created_at ASC, id ASC`,
    [USER_ACTIVE, OFFERING_CS_F25],
  );
  expect(rows.length, "CS101 Fall 2025 needs a seeded document").toBeGreaterThan(0);
  return rows as { id: string; file_name: string }[];
}

/** The mastery events check answers journalled for the seeded student. */
async function guideCheckEvents() {
  return (await queryRaw(
    `SELECT e.event_type, e.delta, e.node_id
       FROM node_mastery_events e
       JOIN graph_nodes n ON n.id = e.node_id
      WHERE n.user_id = $1 AND e.event_type IN ($2, $3)
      ORDER BY e.created_at`,
    [USER_ACTIVE, EVENT_CORRECT, EVENT_INCORRECT],
  )) as { event_type: string; delta: number; node_id: string }[];
}

/**
 * The reader has a whole written guide on screen. The banner is not waited
 * FOR: three scripted sections can be written before the first frame shows
 * it. What must hold is the end state.
 */
async function expectGuideWritten(page: Page): Promise<void> {
  await expect(page.getByTestId("guide-title")).toHaveText(GUIDE_TITLE, {
    timeout: GENERATION_TIMEOUT,
  });
  await expect(page.getByTestId("guide-generating")).toHaveCount(0, {
    timeout: GENERATION_TIMEOUT,
  });
  await expect(page.getByTestId("guide-generation-error")).toHaveCount(0);
  // A section's read toggle is disabled until the section is written.
  await expect(page.getByTestId("guide-section-read-s1")).toBeEnabled();
  // `.skeleton` is the Skeleton primitive's class: none is left in the guide.
  await expect(page.locator("article .skeleton")).toHaveCount(0);
}

/**
 * The run gave its claim back. The stream's last event reaches the reader
 * before that write lands, and a block rewrite needs the claim free, so this
 * is a real precondition for the next step and not only an assertion.
 */
async function expectClaimReleased(guideId: string): Promise<void> {
  await expect
    .poll(async () => (await storedGuide(guideId)).generating_at, {
      message: "the generation claim was not released",
      timeout: LOAD_TIMEOUT,
    })
    .toBeNull();
}

/**
 * A new whole-course CS101 guide, created through the API and written by the
 * reader, which is how every new guide is written: the dialog only inserts the
 * row. Shorter than the dialog, and the dialog has its own journey.
 */
async function openWrittenGuide(page: Page, request: APIRequestContext): Promise<string> {
  const base = `/api/study-guide/${USER_ACTIVE}`;
  const optionsRes = await request.get(`${base}/options`, {
    params: { course_id: COURSE_ID_CS, semester: TERM },
  });
  expect(optionsRes.status(), await optionsRes.text()).toBe(200);
  const options = (await optionsRes.json()) as GuideOptions;
  const wholeCourse = options.scopes.find(scope => scope.kind === "course");
  expect(wholeCourse?.suggested_material_ids.length, "no material to write from").toBeGreaterThan(0);

  const created = await request.post(`${base}/guides`, {
    data: {
      course_id: COURSE_ID_CS,
      semester: TERM,
      scope_kind: "course",
      scope_id: null,
      goal: "exam_prep",
      depth: "standard",
      material_ids: wholeCourse!.suggested_material_ids,
      use_history: true,
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  const guideId = ((await created.json()) as { id: string }).id;

  await page.goto(`/study/guide/${guideId}`);
  await expectGuideWritten(page);
  await expectClaimReleased(guideId);
  return guideId;
}

/**
 * Pick one answer of a check question. `AnswerOption` is only `aria-disabled`
 * while an answer is in flight, which Playwright's click does not wait on.
 */
async function pickCheckOption(page: Page, blockId: string, optionId: string): Promise<void> {
  const option = page.getByTestId(`guide-check-option-${blockId}-${optionId}`);
  await expect(option).not.toHaveAttribute("aria-disabled", "true");
  await option.click();
}

/** Every POST to a guide's generate route this page makes from now on. */
function watchGenerateCalls(page: Page): string[] {
  const calls: string[] = [];
  page.on("request", request => {
    if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/generate")) {
      calls.push(request.url());
    }
  });
  return calls;
}

// ── 1. The acceptance journey ───────────────────────────────────────────────

test("a guide is made in the dialog, written, read, answered, saved and found again", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await requireFunctionMode();
  // The same key the Courses & Semesters hub writes (lib/useActiveSemester.ts;
  // semester-scope.spec.ts drives that hub). Here the term is the fixture.
  await page.addInitScript(term => {
    window.localStorage.setItem("sapling_active_semester", term);
  }, TERM);

  const documents = await classDocuments();
  const documentIds = documents.map(document => document.id);

  // ── The home lists the seeded guide ─────────────────────────────────────
  await page.goto("/study/guide");
  const seededCard = page.getByTestId(`guides-card-${SEEDED_GUIDE.id}`);
  await expect(seededCard).toBeVisible({ timeout: LOAD_TIMEOUT });
  await expect(seededCard).toContainText(SEEDED_GUIDE.title);
  await expect(seededCard).toHaveAttribute("data-status", "ready");
  await expect(page.getByTestId(`guides-card-saved-${SEEDED_GUIDE.id}`)).toHaveCount(0);

  // ── The New study guide dialog ──────────────────────────────────────────
  await page.getByTestId("guides-new").click();
  const dialog = page.getByTestId("guide-new-dialog");
  await expect(dialog).toBeVisible();

  // Class: only the picked term's classes are offered.
  const classSelect = page.getByTestId("guide-new-class");
  const csOption = page.getByTestId(`guide-new-class-option-${COURSE_ID_CS}`);
  await classSelect.click();
  await expect(csOption).toBeVisible();
  await expect(page.getByTestId(`guide-new-class-option-${COURSE_ID_MATH}`)).toHaveCount(0);
  await csOption.click();
  await expect(classSelect).toContainText("CS101");

  // Studying for: this offering's own midterm, never the other class's. An
  // exam never suggests the syllabus; the whole course suggests everything.
  const scopeSelect = page.getByTestId("guide-new-scope");
  const syllabusTile = page.getByTestId(`guide-new-material-${SYLLABUS_DOC}`);
  const midterm = page.getByTestId(`guide-new-scope-option-exam:${EXAM_CS_F25}`);
  await scopeSelect.click();
  await expect(midterm).toBeVisible();
  await expect(page.getByTestId(`guide-new-scope-option-exam:${EXAM_MATH_S26}`)).toHaveCount(0);
  await midterm.click();
  await expect(scopeSelect).toContainText("Midterm Exam");
  await expect(syllabusTile).toHaveAttribute("aria-pressed", "false");

  await scopeSelect.click();
  await page.getByTestId("guide-new-scope-option-course").click();
  await expect(scopeSelect).toContainText("Whole course");
  for (const id of documentIds) {
    await expect(page.getByTestId(`guide-new-material-${id}`)).toHaveAttribute("aria-pressed", "true");
  }
  await expect(page.getByTestId("guide-new-materials-count")).toHaveText(
    `${documentIds.length} of ${documentIds.length} selected`,
  );

  // Goal and depth: neither is the default, so the stored row proves both.
  await page.getByTestId("guide-new-goal-review").click();
  await expect(page.getByTestId("guide-new-goal-review")).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("guide-new-depth-cram").click();
  await expect(page.getByTestId("guide-new-depth-cram")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("guide-new-history")).toHaveAttribute("aria-checked", "true");

  // The planned outline for those choices. No model runs for it.
  const outline = page.getByTestId("guide-new-outline");
  await expect(outline).toHaveAttribute("aria-busy", "false");
  await expect(page.getByTestId("guide-new-outline-section-0")).toHaveAttribute(
    "data-tier",
    /^(mastered|learning|struggling|unexplored)$/,
  );
  await expect(outline.getByTestId("guide-space-bar")).toBeVisible();
  await expect(page.getByTestId("guide-new-outline-minutes")).toHaveText(/^about \d+ min$/);

  await page.getByTestId("guide-new-generate").click();

  // ── The reader writes the guide ─────────────────────────────────────────
  await expect(page).toHaveURL(/\/study\/guide\/[0-9a-f-]{36}$/, { timeout: LOAD_TIMEOUT });
  const guideId = new URL(page.url()).pathname.split("/").pop()!;
  expect(guideId).not.toBe(SEEDED_GUIDE.id);

  await expectGuideWritten(page);
  const sections = page.locator('section[data-testid^="guide-section-"]');
  await expect(sections, THREE_SECTIONS_HINT).toHaveCount(SECTIONS.length);
  for (const section of SECTIONS) {
    await expect(
      page.getByTestId(`guide-section-${section.id}`).getByRole("heading", { level: 3 }),
    ).toHaveText(section.title);
    await expect(page.getByTestId(`guide-section-read-${section.id}`)).toBeEnabled();
    // The rail shows live mastery once nothing is being written.
    await expect(page.getByTestId(`guide-outline-${section.id}`)).toContainText(section.tier);
  }
  await expect(page.getByText(TAKEAWAY)).toBeVisible();
  // More room where the student is weakest.
  await expect(page.getByTestId("guide-space-bar").getByRole("img")).toHaveAttribute(
    "aria-label",
    "Share of the guide per section: " +
      SECTIONS.map(s => `${s.title} ${s.share}%, ${s.tier}`).join("; "),
  );
  // The mastered section is one line until it is opened.
  const mastered = SECTIONS[2].id;
  await expect(page.getByTestId(`guide-section-expand-${mastered}`)).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await expect(page.getByTestId(`guide-block-${itemId(mastered, PLACE.check)}`)).toBeHidden();

  // The first passage cites the first source, and the sources list every one.
  const first = SECTIONS[0].id;
  const prose = page.getByTestId(`guide-prose-${itemId(first, PLACE.prose)}`);
  await expect(prose).toContainText(PROSE_SNIPPET);
  await expect(prose).not.toContainText("[S1]");
  await expect(prose.getByRole("link", { name: `Source: ${documents[0].file_name}` })).toBeVisible();
  for (const document of documents) {
    await expect(page.getByTestId("guide-sources")).toContainText(document.file_name);
  }

  // The row: the dialog's choices, ready, and the content encrypted at rest.
  await expectClaimReleased(guideId);
  const written = await storedGuide(guideId);
  expect(written).toMatchObject({
    user_id: USER_ACTIVE,
    offering_id: OFFERING_CS_F25,
    exam_id: null,
    scope_kind: "course",
    goal: "review",
    depth: "cram",
    use_history: true,
    status: "ready",
    format: 2,
    read_sections: [],
    saved_at: null,
    answers_type: null,
  });
  expect([...written.material_ids].sort()).toEqual([...documentIds].sort());
  expect(written.generated_at).not.toBeNull();
  // Ciphertext, not JSON: a string, and none of the guide's words in it. Both
  // halves are needed, as in tutor.spec.ts: the decrypt helper echoes
  // plaintext back, so decrypt-equality alone would not prove encryption.
  expect(written.content_type).toBe("string");
  expect(written.content_cipher).not.toContain(GUIDE_TITLE);
  expect(written.content_cipher).not.toContain("Recursion");
  const content = await storedContent(guideId);
  expect(content.title).toBe(GUIDE_TITLE);
  expect(content.sections.map(section => section.id)).toEqual(SECTIONS.map(s => s.id));
  expect(content.sections[0].items.map(item => item.id)).toEqual(
    Object.values(PLACE).map(place => itemId(first, place)),
  );

  // ── Skim, and back to Read ──────────────────────────────────────────────
  const skim = page.getByTestId(`guide-skim-${itemId(first, PLACE.prose)}`);
  const unsummarised = itemId(first, PLACE.proseNoSummary);
  const firstSection = page.getByTestId(`guide-section-${first}`);
  await expect(page.getByTestId(`guide-prose-${unsummarised}`)).toContainText(UNSUMMARISED_SNIPPET);
  await expect(skim).toHaveCount(0);

  await page.getByTestId("guide-mode-skim").click();
  await expect(page.getByTestId("guide-mode-skim")).toHaveAttribute("aria-pressed", "true");
  await expect(skim).toHaveText(SKIM_SUMMARY);
  await expect(prose).toHaveCount(0);
  // A passage with no summary is left out of Skim altogether.
  await expect(page.getByTestId(`guide-prose-${unsummarised}`)).toHaveCount(0);
  await expect(page.getByTestId(`guide-skim-${unsummarised}`)).toHaveCount(0);
  await expect(firstSection.getByText(UNSUMMARISED_SNIPPET)).toHaveCount(0);
  for (const place of BLOCK_PLACES) {
    await expect(page.getByTestId(`guide-block-${itemId(first, place)}`)).toBeVisible();
  }

  await page.getByTestId("guide-mode-read").click();
  await expect(prose).toBeVisible();
  await expect(skim).toHaveCount(0);

  // ── Check yourself: only the first answer counts ────────────────────────
  const check = itemId(first, PLACE.check);
  const result = page.getByTestId(`guide-check-result-${check}`);
  const wrongOption = page.getByTestId(`guide-check-option-${check}-${CHECK.wrong}`);
  const rightOption = page.getByTestId(`guide-check-option-${check}-${CHECK.right}`);
  const masteryBefore = await masteryOf(NODE_ID);
  expect(await guideCheckEvents()).toHaveLength(0);

  // Wrong first: a nudge toward the method, and the answer is not given away.
  await pickCheckOption(page, check, CHECK.wrong);
  await expect(result).toHaveText(`Not quite. ${CHECK.explainIncorrect}`);
  await expect(wrongOption).toHaveClass(/answer-option--chosen-wrong/);
  await expect(rightOption).toHaveClass(/answer-option--default/);

  const counted = await guideCheckEvents();
  expect(counted).toHaveLength(1);
  expect(counted[0].event_type).toBe(EVENT_INCORRECT);
  expect(counted[0].node_id).toBe(NODE_ID);
  expect(Number(counted[0].delta)).toBeCloseTo(-MASTERY_PER_WRONG, 6);
  expect(await masteryOf(NODE_ID)).toBeCloseTo(masteryBefore - MASTERY_PER_WRONG, 6);

  // Then the right one: graded and explained, and nothing more is counted.
  await pickCheckOption(page, check, CHECK.right);
  await expect(result).toHaveText(`Correct. ${CHECK.explainCorrect}`);
  await expect(rightOption).toHaveClass(/answer-option--correct/);

  expect(await guideCheckEvents()).toEqual(counted);
  expect(await masteryOf(NODE_ID)).toBeCloseTo(masteryBefore - MASTERY_PER_WRONG, 6);
  // The stored answer is the first one, encrypted.
  const answered = await storedGuide(guideId);
  expect(answered.answers_type).toBe("string");
  expect(answered.answers_cipher).not.toContain(check);
  expect(JSON.parse(await decryptText(answered.answers_cipher ?? ""))).toEqual({
    [check]: { option_id: CHECK.wrong, correct: false },
  });

  // ── Mark a section read ─────────────────────────────────────────────────
  const readToggle = page.getByTestId(`guide-section-read-${first}`);
  await expect(page.getByTestId("guide-progress")).toContainText(
    `0 of ${SECTIONS.length} sections read`,
  );
  await readToggle.click();
  await expect(readToggle).toHaveAttribute("aria-pressed", "true");
  await expect(readToggle).toHaveText("Read");
  await expect(page.getByTestId("guide-progress")).toContainText(
    `1 of ${SECTIONS.length} sections read`,
  );
  await expect(page.getByTestId(`guide-outline-read-${first}`)).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  // The mark shows at once and is saved behind it.
  await expect.poll(async () => (await storedGuide(guideId)).read_sections).toEqual([first]);

  // ── Save to the Library from the three-dot menu ─────────────────────────
  const menu = page.getByTestId("guide-menu");
  await menu.click();
  await page.getByTestId("guide-menu-save").click();
  await expect(page.getByTestId("guide-menu-saved")).toContainText("Saved to Library");
  await expect(page.getByTestId("guide-menu-save")).toHaveCount(0);
  expect((await storedGuide(guideId)).saved_at).not.toBeNull();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveAttribute("aria-expanded", "false");

  // ── Back on the home: the new card, saved, ahead of the seeded one ──────
  await page.getByTestId("back-link").click();
  await expect(page).toHaveURL(/\/study\/guide$/);
  const card = page.getByTestId(`guides-card-${guideId}`);
  await expect(card).toBeVisible({ timeout: LOAD_TIMEOUT });
  await expect(card).toContainText(GUIDE_TITLE);
  await expect(card).toContainText(COURSE_NAME_CS);
  await expect(card).toHaveAttribute("data-status", "ready");
  await expect(page.getByTestId(`guides-card-saved-${guideId}`)).toContainText("Saved");
  await expect(card.getByTestId("guide-space-bar")).toBeVisible();
  await expect(page.getByTestId(`guides-card-room-${guideId}`)).toContainText(
    `Most room: ${SECTIONS[0].title}`,
  );
  await expect(page.getByTestId(`guides-card-sections-${guideId}`).locator("dd")).toHaveText(
    String(SECTIONS.length),
  );
  await expect(page.getByTestId(`guides-card-blocks-${guideId}`).locator("dd")).toHaveText(
    String(SECTIONS.length * BLOCK_PLACES.length),
  );
  await expect(page.getByTestId(`guides-card-practice-${guideId}`).locator("dd")).toHaveText(
    String(SECTIONS.length),
  );
  // Most recent first is the default sort.
  await expect(page.getByTestId("guides-grid").getByRole("link").first()).toHaveAttribute(
    "data-testid",
    `guides-card-${guideId}`,
  );
  await expect(page.getByTestId(`guides-card-saved-${SEEDED_GUIDE.id}`)).toHaveCount(0);

  // ── In the Library, by the reader's own "Saved to Library" link ─────────
  await card.click();
  await expect(page).toHaveURL(new RegExp(`/study/guide/${guideId}$`));
  await expect(page.getByTestId("guide-title")).toHaveText(GUIDE_TITLE, { timeout: LOAD_TIMEOUT });
  await page.getByTestId("guide-menu").click();
  await page.getByTestId("guide-menu-saved").click();
  await expect(page).toHaveURL(/\/library$/);

  const libraryCard = page.getByTestId(`library-guide-${guideId}`);
  await expect(libraryCard).toBeVisible({ timeout: LOAD_TIMEOUT });
  await expect(libraryCard).toContainText(GUIDE_TITLE);
  await expect(libraryCard).toContainText(COURSE_NAME_CS);
  // Only saved guides are in the Library.
  await expect(page.getByTestId(`library-guide-${SEEDED_GUIDE.id}`)).toHaveCount(0);

  // The Library card opens the reader on that guide, as the student left it.
  await libraryCard.click();
  await expect(page).toHaveURL(new RegExp(`/study/guide/${guideId}$`));
  await expect(page.getByTestId("guide-title")).toHaveText(GUIDE_TITLE, { timeout: LOAD_TIMEOUT });
  await expect(page.getByTestId("guide-generating")).toHaveCount(0);
  await expect(page.getByTestId(`guide-section-read-${first}`)).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

// ── 2. One block, regenerated ───────────────────────────────────────────────

test("regenerating one block rewrites that block and nothing else", async ({ page, request }) => {
  test.setTimeout(120_000);
  await requireFunctionMode();
  const guideId = await openWrittenGuide(page, request);

  const section = SECTIONS[0].id;
  const keyTermsId = itemId(section, PLACE.keyTerms);
  const keyTerms = page.getByTestId(`guide-block-${keyTermsId}`);
  const comparison = page.getByTestId(`guide-block-${itemId(section, PLACE.comparison)}`);
  const conceptMap = page.getByTestId(`guide-block-${itemId(section, PLACE.conceptMap)}`);
  const passage = page.getByTestId(`guide-prose-${itemId(section, PLACE.proseNoSummary)}`);

  await expect(keyTerms).toContainText(KEY_TERMS.title);
  await expect(keyTerms).toContainText(KEY_TERMS.onlyTerm);
  const before = {
    comparison: await comparison.textContent(),
    conceptMap: await conceptMap.textContent(),
    passage: await passage.textContent(),
    itemIds: (await storedContent(guideId)).sections[0].items.map(item => item.id),
  };

  await page.getByTestId(`guide-block-regenerate-${keyTermsId}`).click();

  // The same block, by the same testid, with the rewritten content.
  await expect(keyTerms).toContainText(REWRITTEN_KEY_TERMS.title);
  await expect(keyTerms).toContainText(REWRITTEN_KEY_TERMS.onlyTerm);
  await expect(keyTerms).not.toContainText(KEY_TERMS.title);
  await expect(keyTerms).not.toContainText(KEY_TERMS.onlyTerm);
  await expect(keyTerms).toHaveAttribute("aria-label", `Key terms: ${REWRITTEN_KEY_TERMS.title}`);
  await expect(page.getByTestId(`guide-block-regenerate-${keyTermsId}`)).toBeEnabled();

  // Its neighbours are as they were.
  expect(await comparison.textContent()).toBe(before.comparison);
  expect(await conceptMap.textContent()).toBe(before.conceptMap);
  expect(await passage.textContent()).toBe(before.passage);
  await expect(page.getByTestId("guide-title")).toHaveText(GUIDE_TITLE);

  // Stored: one block changed, in place, and the claim it took is back.
  await expectClaimReleased(guideId);
  const content = await storedContent(guideId);
  expect(content.sections[0].items.map(item => item.id)).toEqual(before.itemIds);
  const rewritten = itemsOf(content).filter(
    item => item.type === "key_terms" && item.title === REWRITTEN_KEY_TERMS.title,
  );
  expect(rewritten.map(item => item.id)).toEqual([keyTermsId]);
  expect((await storedGuide(guideId)).status).toBe("ready");

  // And it is what a later visit reads.
  await page.reload();
  await expect(keyTerms).toContainText(REWRITTEN_KEY_TERMS.title, { timeout: LOAD_TIMEOUT });
  await expect(comparison).toBeVisible();
});

// ── 3. The seeded guide opens as a full guide ───────────────────────────────

test("the seeded guide opens whole, with nothing generated", async ({ page }) => {
  const generateCalls = watchGenerateCalls(page);

  await page.goto("/study/guide");
  await page.getByTestId(`guides-card-${SEEDED_GUIDE.id}`).click();
  await expect(page).toHaveURL(new RegExp(`/study/guide/${SEEDED_GUIDE.id}$`));
  await expect(page.getByTestId("guide-title")).toHaveText(SEEDED_GUIDE.title, {
    timeout: LOAD_TIMEOUT,
  });
  await expect(page.getByTestId("guide-generating")).toHaveCount(0);
  await expect(page.getByTestId("guide-generation-error")).toHaveCount(0);

  // Three written sections (db/seed_local_rich.py::_cs_midterm_guide).
  const titles = { s1: "Variables and types", s2: "Control flow", s3: "Functions and recursion" };
  await expect(page.locator('section[data-testid^="guide-section-"]')).toHaveCount(3);
  for (const [id, title] of Object.entries(titles)) {
    await expect(
      page.getByTestId(`guide-section-${id}`).getByRole("heading", { level: 3 }),
    ).toHaveText(title);
    await expect(page.getByTestId(`guide-section-read-${id}`)).toBeEnabled();
  }
  await expect(page.locator("article .skeleton")).toHaveCount(0);
  await expect(page.getByTestId("guide-progress")).toContainText("0 of 3 sections read");
  await expect(page.getByTestId("guide-sources")).toContainText("cs101-syllabus.pdf");

  // Every block the seed wrote, by the kind and title its frame names.
  const blocks = {
    "s1-i2": "Key terms: Key terms",
    "s1-i3": "Comparison: Assignment and comparison",
    "s2-i2": "Formula: Passes of a counting loop",
    "s2-i3": "Worked example: Count the passes",
    "s2-i4": "Check yourself",
    "s3-i2": "Concept map: What this section builds on",
    "s3-i3": "Check yourself",
  };
  for (const [id, label] of Object.entries(blocks)) {
    await expect(page.getByTestId(`guide-block-${id}`)).toHaveAttribute("aria-label", label);
  }
  await expect(page.getByTestId("guide-prose-s2-i1")).toContainText("Control flow is the order");

  // The mastered section is one line, and opens.
  const expand = page.getByTestId("guide-section-expand-s1");
  await expect(expand).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("guide-outline-s1")).toContainText("Mastered, one line");
  await expect(page.getByTestId("guide-block-s1-i2")).toBeHidden();
  await expect(page.getByTestId("guide-prose-s1-i1")).toBeHidden();
  await expand.click();
  await expect(expand).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("guide-block-s1-i2")).toBeVisible();
  await expect(page.getByTestId("guide-prose-s1-i1")).toBeVisible();
  await expand.click();
  await expect(page.getByTestId("guide-block-s1-i2")).toBeHidden();

  // The worked example shows one more step at a time.
  const example = page.getByTestId("guide-block-s2-i3");
  const next = page.getByTestId("guide-step-next-s2-i3");
  const stepOne = example.getByText("List the values");
  const stepTwo = example.getByText("Count them");
  await expect(example).toContainText("0 of 2 steps");
  await expect(stepOne).toBeHidden();
  await next.click();
  await expect(example).toContainText("1 of 2 steps");
  await expect(stepOne).toBeVisible();
  await expect(stepTwo).toBeHidden();
  await next.click();
  await expect(example).toContainText("2 of 2 steps");
  await expect(stepTwo).toBeVisible();
  await expect(next).toHaveCount(0);
  await page.getByTestId("guide-step-reset-s2-i3").click();
  await expect(example).toContainText("0 of 2 steps");
  await expect(stepOne).toBeHidden();

  // The concept map joins mastery as it is now.
  await expect(page.getByTestId("guide-concept-s3-i2-0")).toContainText("Variables and Types");
  await expect(page.getByTestId("guide-concept-s3-i2-0")).toContainText("Mastered");
  await expect(page.getByTestId("guide-concept-s3-i2-2")).toContainText("Recursion");
  await expect(page.getByTestId("guide-concept-s3-i2-2")).toContainText("Struggling");

  // The questions are open and unanswered.
  for (const check of ["s2-i4", "s3-i3"]) {
    await expect(page.getByTestId(`guide-check-option-${check}-b`)).toBeVisible();
    await expect(page.getByTestId(`guide-check-result-${check}`)).toHaveCount(0);
  }

  // Nothing was generated: no request, and the row is as the seed wrote it.
  expect(generateCalls).toEqual([]);
  const stored = await queryRaw(
    `SELECT status, generating_at, generated_at = $2::timestamptz AS untouched
       FROM study_guides
      WHERE id = $1`,
    [SEEDED_GUIDE.id, SEEDED_GUIDE.madeAt],
  );
  expect(stored).toEqual([{ status: "ready", generating_at: null, untouched: true }]);
});

// ── 4. A reload ─────────────────────────────────────────────────────────────

test("a reload brings back the guide, its read mark and its answered question", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  await requireFunctionMode();
  const guideId = await openWrittenGuide(page, request);

  const section = SECTIONS[0].id;
  const check = itemId(section, PLACE.check);
  const readToggle = page.getByTestId(`guide-section-read-${section}`);
  const result = page.getByTestId(`guide-check-result-${check}`);
  const rightOption = page.getByTestId(`guide-check-option-${check}-${CHECK.right}`);
  const keyTerms = page.getByTestId(`guide-block-${itemId(section, PLACE.keyTerms)}`);
  const sections = page.locator('section[data-testid^="guide-section-"]');
  const masteryBefore = await masteryOf(NODE_ID);

  // Read a section, and wait for the mark to be stored before the next write.
  await readToggle.click();
  await expect(readToggle).toHaveAttribute("aria-pressed", "true");
  await expect.poll(async () => (await storedGuide(guideId)).read_sections).toEqual([section]);

  // Answer the question right the first time.
  await pickCheckOption(page, check, CHECK.right);
  await expect(result).toHaveText(`Correct. ${CHECK.explainCorrect}`);
  const events = await guideCheckEvents();
  expect(events.map(event => event.event_type)).toEqual([EVENT_CORRECT]);
  expect(await masteryOf(NODE_ID)).toBeCloseTo(masteryBefore + MASTERY_PER_CORRECT, 6);

  const before = { sections: await sections.count(), keyTerms: await keyTerms.textContent() };
  const generateCalls = watchGenerateCalls(page);
  await page.reload();

  // The same written guide, read from the row: nothing is generated again.
  await expect(page).toHaveURL(new RegExp(`/study/guide/${guideId}$`));
  await expect(page.getByTestId("guide-title")).toHaveText(GUIDE_TITLE, { timeout: LOAD_TIMEOUT });
  await expect(page.getByTestId("guide-generating")).toHaveCount(0);
  await expect(sections).toHaveCount(before.sections);
  await expect(page.locator("article .skeleton")).toHaveCount(0);
  expect(await keyTerms.textContent()).toBe(before.keyTerms);

  // The read mark, in the section and in the rail.
  await expect(readToggle).toHaveAttribute("aria-pressed", "true");
  await expect(readToggle).toHaveText("Read");
  await expect(page.getByTestId(`guide-outline-read-${section}`)).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  // The answer, with its explanation, without being asked again.
  await expect(result).toHaveText(`Correct. ${CHECK.explainCorrect}`);
  await expect(rightOption).toHaveClass(/answer-option--correct/);

  expect(generateCalls).toEqual([]);
  expect(await guideCheckEvents()).toEqual(events);
});
