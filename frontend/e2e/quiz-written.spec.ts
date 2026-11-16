import { expect, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { NODE_ID, preAckDisclaimer, openQuizHome, expectResults, appAttempts, SUBMIT_TIMEOUT } from "./support/quiz";

// Requires the migrated, seeded function-mode stack. The fixed handler in
// agents/function_handlers_e2e.py emits short_answer, numeric, symbolic here.
test("written quiz: equivalent answers survive reload and produce persisted results", async ({ page }) => {
  test.setTimeout(180_000);
  await preAckDisclaimer(page);
  await page.addInitScript(() => {
    localStorage.setItem("sapling_quiz_prefs", JSON.stringify({ count: 3, difficulty: "medium", feedback: "at-end", questionFormat: "mixed" }));
  });
  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);
  await page.getByTestId("quiz-start").click();
  const written = page.getByTestId("quiz-written-answer");
  await expect(written).toBeVisible({ timeout: SUBMIT_TIMEOUT });
  // The grading rules are on screen, not only in the visually hidden keyboard hint.
  await expect(page.getByTestId("quiz-format-hint")).toBeVisible();
  await expect(page.getByTestId("quiz-format-hint")).toContainText("Write a brief answer");
  await written.fill("termination condition");
  await page.getByTestId("quiz-submit-answer").click();
  await expect(page.getByTestId("quiz-panel")).toContainText("What value does the graph show at step 1?", { timeout: SUBMIT_TIMEOUT });

  // Resume the local drafts against the server attempt.
  const attempts = await appAttempts();
  expect(attempts).toHaveLength(1);
  await page.goto(`/quiz?attempt=${attempts[0].id}`);
  await expect(page.getByTestId("quiz-panel")).toContainText("What value does the graph show at step 1?", { timeout: SUBMIT_TIMEOUT });
  await expect(page.getByTestId("quiz-format-hint")).toContainText("Enter only the number");
  await written.fill("50%");
  // The numeric input reads the percentage back before it is submitted.
  await expect(page.getByTestId("quiz-written-readback")).toContainText("Reads as 0.5");
  await page.getByTestId("quiz-submit-answer").click();
  await expect(page.getByTestId("quiz-panel")).toContainText("Expand 2(x + 1).", { timeout: SUBMIT_TIMEOUT });
  // The algebra keys insert at the cursor: "( )" leaves it between the brackets.
  await written.fill("2");
  await page.getByTestId("quiz-key-brackets").click();
  await page.keyboard.type("x + 1");
  await expect(written).toHaveValue("2(x + 1)");
  // A valid expression needs no read-back: the field itself shows it as read.
  await expect(page.getByTestId("quiz-written-readback")).toHaveCount(0);
  // Enter submits from the written input, as it does from an answer row.
  await written.press("Enter");
  await expectResults(page);
  const completed = await appAttempts();
  expect(completed[0].score).toBe(3);
  expect(completed[0].total).toBe(3);
  expect(completed[0].completed_at).toBeTruthy();
  const responses = await queryRaw("SELECT id FROM quiz_responses WHERE attempt_id = $1", [attempts[0].id]);
  expect(responses).toHaveLength(0);
  await expect(page.getByTestId("quiz-correct-1")).toContainText("A base case");
  await expect(page.getByTestId("quiz-correct-2")).toContainText("0.5");
  await expect(page.getByTestId("quiz-correct-3")).toContainText("Distribute 2");
});
