/**
 * W7 kit Sort on the planned short_answer path (function mode).
 *
 * Flags on for one student → FORMAT short_answer → `build_message` adds
 * `KIT: sort` → first question mounts `quiz-sort`. See
 * docs/learning-loop/w7-generation-emit.md.
 */
import { expect, test } from "./support/fixtures";
import { setUserFlag } from "./support/db";
import { loopOffLane } from "./support/lane";
import { PREFS_KEY } from "@/lib/quiz/session";
import {
  GENERATE_TIMEOUT,
  NODE_ID,
  SUBMIT_TIMEOUT,
  expectResults,
  openQuizHome,
  preAckDisclaimer,
} from "./support/quiz";
import { USER_ACTIVE } from "./support/stack";

/** agents/function_handlers_e2e.py::E2E_CHECK_ITEM_FINAL_ANSWER, the planned
 *  written fixture's key. */
const PLANNED_WRITTEN_ANSWER = "The size of each parameter update step";

const LOOP_ON_ONLY = "kit Sort needs the learning loop: default lane only";

const QUIZ_FLAGS = [
  "quiz_concept_plan",
  "quiz_planned_questions",
  "quiz_item_gates",
] as const;

test("planned short_answer quiz mounts Sort and grades a correct placement", async ({ page }) => {
  test.skip(loopOffLane, LOOP_ON_ONLY);
  test.setTimeout(180_000);

  for (const key of QUIZ_FLAGS) await setUserFlag(key, USER_ACTIVE, "on");
  await preAckDisclaimer(page);
  await page.addInitScript(
    ([key]) => {
      window.localStorage.setItem(
        key,
        JSON.stringify({
          // A count off /api/quiz/config's options (3, 5, 10) is dropped back
          // to the default 5 by loadPrefs, so ask for the smallest real one.
          count: 3,
          difficulty: "medium",
          feedback: "at-end",
          questionFormat: "short_answer",
        }),
      );
    },
    [PREFS_KEY],
  );

  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);
  await page.getByTestId("quiz-start").click();

  const sort = page.getByTestId("quiz-sort");
  await expect(sort).toBeVisible({ timeout: GENERATE_TIMEOUT });
  await expect(sort).toHaveAttribute("data-complete", "false");

  await page.getByTestId("quiz-sort-item-ecoli").click();
  await page.getByRole("button", { name: "Place in Prokaryote" }).click();
  await page.getByTestId("quiz-sort-item-yeast").click();
  await page.getByRole("button", { name: "Place in Eukaryote" }).click();
  await expect(sort).toHaveAttribute("data-complete", "true");

  await page.getByTestId("quiz-submit-answer").click();

  // Slots 2 and 3 are the planned written fixture (no kit): answer them right.
  const written = page.getByTestId("quiz-written-answer");
  for (const n of [2, 3]) {
    await expect(page.getByTestId("quiz-panel")).toContainText(`E2E planned written question ${n}`, {
      timeout: SUBMIT_TIMEOUT,
    });
    await written.fill(PLANNED_WRITTEN_ANSWER);
    await page.getByTestId("quiz-submit-answer").click();
  }
  await expectResults(page);
  await expect(page.getByTestId("quiz-results-score")).toHaveText("3 of 3 correct", {
    timeout: SUBMIT_TIMEOUT,
  });
});
