import { test, expect } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { createHash } from "node:crypto";

const recursionId = createHash("sha256").update("recursion").digest("hex").slice(0, 32);

test("course checklist persists study checks without manufacturing mastery", async ({ page }) => {
  await page.goto("/tree");
  await page.getByTestId("graph-course-filter-rich-course-cs101").click();
  await page.getByTestId("topic-checklist-toggle").click();
  const checkbox = page.getByTestId(`topic-checklist-check-${recursionId}`);
  await expect(checkbox).toBeEnabled();
  await expect(page.getByTestId(`topic-checklist-topic-${recursionId}`)).toContainText("Needs review");
  await checkbox.check();
  await expect(checkbox).toBeChecked();
  await expect(checkbox).toBeEnabled();

  const cache = await queryRaw("SELECT content FROM topic_checklists");
  expect(cache).toHaveLength(1);
  expect(String(cache[0].content)).not.toContain("Recursion");
  const progress = await queryRaw("SELECT * FROM topic_checklist_progress");
  expect(progress).toHaveLength(1);
  const graph = await queryRaw("SELECT mastery_score FROM graph_nodes WHERE id = $1", ["rich-node-cs-recursion"]);
  expect(Number(graph[0].mastery_score)).toBe(0.25);

  await page.reload();
  await page.getByTestId("graph-course-filter-rich-course-cs101").click();
  await page.getByTestId("topic-checklist-toggle").click();
  await expect(page.getByTestId(`topic-checklist-check-${recursionId}`)).toBeChecked();
});
