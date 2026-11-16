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
  await expect(page.getByText("Part 1 of 3")).toBeVisible();
  await expect(page.getByRole("img", { name: "Value by Step" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /What is the condition that stops/ })).toBeVisible();
  await expect(page.getByTestId("quiz-format-hint")).toHaveCount(0);
  await expect(page.getByText("Graph data")).toHaveCount(0);
  await written.fill("termination condition");
  await page.getByTestId("quiz-submit-answer").click();
  await expect(page.getByTestId("quiz-panel")).toContainText("What value does the graph show at step 1?", { timeout: SUBMIT_TIMEOUT });

  // Resume on the server, without the browser's saved question state.
  const attempts = await appAttempts();
  expect(attempts).toHaveLength(1);
  await page.evaluate(() => localStorage.removeItem("sapling_quiz_session"));
  await page.goto(`/quiz?attempt=${attempts[0].id}`);
  await expect(page.getByTestId("quiz-panel")).toContainText("What value does the graph show at step 1?", { timeout: SUBMIT_TIMEOUT });
  await expect(page.getByTestId("quiz-format-hint")).toContainText("Enter only the number");
  await written.fill("50%");
  await page.setViewportSize({ width: 390, height: 720 });
  await expect(page.getByRole("img", { name: "Value by Step" })).toBeInViewport({ ratio: 1 });
  await expect(written).toBeInViewport({ ratio: 1 });
  await expect(page.getByTestId("quiz-submit-answer")).toBeInViewport({ ratio: 1 });
  await expect(page.getByTestId("quiz-written-readback")).toHaveCount(0);
  await page.getByTestId("quiz-submit-answer").click();
  await expect(page.getByTestId("quiz-panel")).toContainText("Expand 2(x + 1).", { timeout: SUBMIT_TIMEOUT });
  await written.fill("2(");
  await expect(page.getByTestId("quiz-submit-answer")).toBeDisabled();
  await written.press("Enter");
  await expect(page.getByTestId("quiz-panel")).toContainText("Expand 2(x + 1).");
  await written.fill("2(x + 1)");
  await expect(written).toHaveValue("2(x + 1)");
  await expect(page.getByTestId("quiz-written-readback")).toHaveCount(0);
  // Enter submits from the written input, as it does from an answer row.
  await written.press("Enter");
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

test("a missed part can earn practice credit once after submission", async ({ page }) => {
  test.setTimeout(180_000);
  await preAckDisclaimer(page);
  await page.addInitScript(() => {
    localStorage.setItem("sapling_quiz_prefs", JSON.stringify({ count: 3, difficulty: "medium", feedback: "at-end", questionFormat: "mixed" }));
  });
  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);
  await page.getByTestId("quiz-start").click();
  const written = page.getByTestId("quiz-written-answer");
  await expect(page.getByText("Part 1 of 3")).toBeVisible({ timeout: SUBMIT_TIMEOUT });
  await page.getByRole("button", { name: "Skip question" }).click();
  await expect(page.getByText("Part 2 of 3")).toBeVisible();
  await written.fill("0.25");
  await page.getByTestId("quiz-submit-answer").click();

  const retry = page.getByRole("region", { name: "Retry for partial credit" });
  await expect(retry.getByText("Try again", { exact: true })).toBeVisible();
  await expect(retry.getByText(/Previous answer/)).toContainText("0.25");
  await expect(page.getByText("The point at step 1 has a value of 0.5.")).toHaveCount(0);
  await retry.getByRole("textbox").fill("50%");
  await retry.getByRole("button", { name: "Submit retry" }).click();
  await expect(retry.getByText(/earned ½ practice point/)).toBeVisible();
  await page.getByTestId("quiz-next").click();

  await expect(page.getByText("Part 3 of 3")).toBeVisible();
  await written.fill("2(x + 1)");
  await page.getByTestId("quiz-submit-answer").click();
  await expectResults(page);

  await expect(page.getByTestId("quiz-missed-1")).toContainText("Skipped");
  await expect(page.getByTestId("quiz-missed-2")).toContainText("0.5 of 1 point");
  await expect(page.getByTestId("quiz-missed-2")).toContainText("The point at step 1 has a value of 0.5.");
  await expect(page.getByTestId("quiz-correct-3")).toContainText("Distribute 2 to each term");
  await expect(page.getByTestId("quiz-results-score")).toContainText("1 of 3 correct");
  await expect(page.getByText("1.5 of 3 practice points with retries")).toBeVisible();
});
