import { expect, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { decryptTexts } from "./support/decrypt";
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
  await written.fill("termination condition");
  await page.getByTestId("quiz-submit-answer").click();
  await expect(page.getByTestId("quiz-panel")).toContainText("E2E written question 2", { timeout: SUBMIT_TIMEOUT });

  // Resume on the server, without the browser's saved question state.
  const attempts = await appAttempts();
  expect(attempts).toHaveLength(1);
  await page.evaluate(() => localStorage.removeItem("sapling_quiz_session"));
  await page.goto(`/quiz?attempt=${attempts[0].id}`);
  await expect(page.getByTestId("quiz-panel")).toContainText("E2E written question 2", { timeout: SUBMIT_TIMEOUT });
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

test("written quiz: incorrect answers show their actual response and expected answer on phone and desktop", async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await preAckDisclaimer(page);
  await page.addInitScript(() => {
    localStorage.setItem("sapling_quiz_prefs", JSON.stringify({ count: 3, difficulty: "medium", feedback: "at-end", questionFormat: "mixed" }));
  });
  await openQuizHome(page, `/quiz?concept=${NODE_ID}`);
  await page.getByTestId("quiz-start").click();
  const cases = [
    { answer: "it continues without terminating", expected: "base case" },
    { answer: "7", expected: "0.5" },
    { answer: "x^2", expected: "2x+2" },
  ];
  const questionIds: string[] = [];
  for (const [index, fixture] of cases.entries()) {
    await expect(page.getByTestId("quiz-panel")).toContainText(`E2E written question ${index + 1}`, { timeout: SUBMIT_TIMEOUT });
    await page.getByTestId("quiz-written-answer").fill(fixture.answer);
    const recorded = page.waitForResponse((response) => response.request().method() === "POST"
      && /^\/api\/quiz\/attempts\/[^/]+\/answer$/.test(new URL(response.url()).pathname));
    await page.getByTestId("quiz-submit-answer").click();
    const response = await recorded;
    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result).toMatchObject({ question_index: index, is_correct: false,
      answer_text: fixture.answer, correct_answer: fixture.expected });
    questionIds.push(String(result.question_id));
  }
  await expectResults(page);
  await expect(page.getByTestId("quiz-results-score")).toHaveText("0 of 3 correct");
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 950 });
    for (const [index, fixture] of cases.entries()) {
      const missed = page.getByTestId(`quiz-missed-${questionIds[index]}`);
      await expect(missed).toBeVisible();
      await expect(missed).toContainText(`Your answer: ${fixture.answer} · Expected: ${fixture.expected}`);
      await expect(missed).not.toContainText("You chose Your answer");
    }
    const geometry = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth }));
    expect(geometry.content).toBeLessThanOrEqual(geometry.viewport);
  }
  const attempts = await appAttempts();
  expect(attempts).toHaveLength(1);
  expect(attempts[0]).toMatchObject({ score: 0, total: 3 });
  expect(attempts[0].completed_at).toBeTruthy();
  const responses = await queryRaw(
    "SELECT selected_index, answer_text, is_correct FROM quiz_responses WHERE attempt_id = $1 ORDER BY question_index",
    [attempts[0].id],
  );
  expect(responses).toHaveLength(3);
  const ciphertext = responses.map((response) => {
    expect(response.selected_index).toBeNull();
    expect(response.is_correct).toBe(false);
    expect(typeof response.answer_text).toBe("string");
    expect(String(response.answer_text)).not.toMatch(/^\s*\{/); // no plaintext JSON at rest
    return String(response.answer_text);
  });
  const plaintext = await decryptTexts(ciphertext);
  for (const [index, value] of plaintext.entries()) {
    expect(ciphertext[index]).not.toBe(value);
    expect(JSON.parse(value)).toEqual({ text: cases[index].answer });
  }
  // Deterministic-key legacy quiz formats retain the conservative MC bucket;
  // they must not become strong, rubric-graded free-response observations.
  const evidence = await queryRaw(
    "SELECT channel, correct, reason, planning_observation FROM node_mastery_events WHERE node_id = $1 AND event_type = 'evidence' ORDER BY created_at,evidence_seq",
    [NODE_ID],
  );
  expect(evidence).toHaveLength(3);
  for (const event of evidence) expect(event).toMatchObject({ channel: "mc", correct: false,
    reason: "evidence:mc", planning_observation: null });
});
