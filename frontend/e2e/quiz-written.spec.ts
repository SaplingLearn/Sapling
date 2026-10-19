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
  await expect(page.getByTestId("quiz-panel")).toContainText("E2E written question 2", { timeout: SUBMIT_TIMEOUT });

  // Resume on the server, without the browser's saved question state.
  const attempts = await appAttempts();
  expect(attempts).toHaveLength(1);
  await page.evaluate(() => localStorage.removeItem("sapling_quiz_session"));
  await page.goto(`/quiz?attempt=${attempts[0].id}`);
  await expect(page.getByTestId("quiz-panel")).toContainText("E2E written question 2", { timeout: SUBMIT_TIMEOUT });
  await expect(page.getByTestId("quiz-format-hint")).toContainText("Enter only the number");
  await written.fill("50%");
  await page.getByTestId("quiz-submit-answer").click();
  await expect(page.getByTestId("quiz-panel")).toContainText("E2E written question 3", { timeout: SUBMIT_TIMEOUT });
  await written.fill("2(x + 1)");
  await page.getByTestId("quiz-submit-answer").click();
  await expectResults(page);
  const completed = await appAttempts();
  expect(completed[0].score).toBe(3);
  expect(completed[0].total).toBe(3);
  expect(completed[0].completed_at).toBeTruthy();
  const responses = await queryRaw("SELECT selected_index, answer_text, is_correct FROM quiz_responses WHERE attempt_id = $1 ORDER BY question_index", [attempts[0].id]);
  expect(responses).toHaveLength(3);
  for (const response of responses) {
    expect(response.selected_index).toBeNull();
    expect(response.answer_text).toBeTruthy();
    expect(response.is_correct).toBe(true);
  }
});
