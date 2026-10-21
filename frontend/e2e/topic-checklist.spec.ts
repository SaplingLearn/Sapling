import { test, expect } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { createHash } from "node:crypto";

const recursionId = createHash("sha256").update("recursion").digest("hex").slice(0, 32);

test("assessment plan persists sessions without manufacturing topic mastery", async ({ page }) => {
  const exam = new Date();
  exam.setDate(exam.getDate() + 10);
  const examDate = `${exam.getFullYear()}-${String(exam.getMonth() + 1).padStart(2, "0")}-${String(exam.getDate()).padStart(2, "0")}`;
  await page.goto("/tree");
  await page.getByTestId("graph-course-filter-rich-course-cs101").click();
  await page.getByTestId("study-plan-toggle").click();
  await page.getByTestId("study-plan-create").click();
  await page.getByTestId("study-plan-title").fill("Recursion midterm");
  await page.getByTestId("study-plan-exam-date").fill(examDate);
  await page.getByTestId("study-plan-coverage").fill("Recursion");
  await page.getByTestId("study-plan-generate").click();
  const checkbox = page.locator('[data-testid^="study-plan-session-"]').first();
  await expect(checkbox).toBeEnabled();
  const sessionId = await checkbox.getAttribute("data-testid");
  await expect(page.getByTestId(`study-plan-topic-${recursionId}`)).toContainText("Not started");
  await checkbox.check();
  await expect(checkbox).toBeChecked();
  await expect(checkbox).toBeEnabled();

  await expect(page.getByTestId(`study-plan-topic-${recursionId}`)).toContainText("Not started");

  const cache = await queryRaw("SELECT content, version FROM assessment_study_plans");
  expect(cache).toHaveLength(1);
  expect(String(cache[0].content)).not.toContain("Recursion");
  expect(Number(cache[0].version)).toBe(2);
  const graph = await queryRaw("SELECT mastery_score FROM graph_nodes WHERE id = $1", ["rich-node-cs-recursion"]);
  expect(Number(graph[0].mastery_score)).toBe(0.25);

  await page.reload();
  await page.getByTestId("graph-course-filter-rich-course-cs101").click();
  await page.getByTestId("study-plan-toggle").click();
  await expect(page.getByTestId(sessionId!)).toBeChecked();
});
