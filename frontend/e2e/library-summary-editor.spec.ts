/**
 * Journey: the core editable-summary loop (library-summary-editor design,
 * docs/superpowers/specs/2026-10-11-library-summary-editor-design.md).
 *
 * Reuses the same upload flow as upload.spec.ts to get a real document with
 * a real summary doc, then drives: open the summary → highlight text →
 * ask the agent → keep the suggestion → history shows it and can restore →
 * deleting the source document cascades to the summary doc.
 *
 * Same determinism requirement as upload.spec.ts: SAPLING_MODEL_MODE=function
 * SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e make e2e-up.
 */
import path from "node:path";

import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import { BACKEND_URL, USER_ACTIVE } from "./support/stack";

const FIXTURE_PDF = path.join(__dirname, "fixtures", "upload-journey.pdf");
const FIXTURE_NAME = "upload-journey.pdf";

// Mirrors backend/agents/function_handlers_e2e.py's E2E_SUMMARY_EDIT_PROPOSAL
// (added in Task 11) — keep in sync with that module.
const SCRIPTED_SUMMARY_EDIT = "This is the deterministic scripted rewrite for the E2E summary-edit journey.";

test("highlight, ask, keep, and restore an earlier version of a summary doc", async ({ page }) => {
  const health = (await (await fetch(`${BACKEND_URL}/api/health`)).json()) as { model_mode?: string };
  expect(
    health.model_mode,
    "Stack is not in deterministic model mode. Reboot it with:\n" +
      "  SAPLING_MODEL_MODE=function " +
      "SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e make e2e-up",
  ).toBe("function");

  // ── Upload, same as upload.spec.ts ────────────────────────────────────
  await page.goto("/library");
  const uploadButton = page.getByTestId("library-upload");
  await expect(uploadButton).toBeEnabled();
  await uploadButton.click();
  await page.getByTestId("upload-modal-file-input").setInputFiles(FIXTURE_PDF);
  await expect(page.getByTestId("upload-modal-file-row-0")).toBeVisible();
  await page.getByTestId("upload-modal-submit").click();
  const doneButton = page.getByTestId("upload-modal-done");
  await expect(doneButton).toBeVisible({ timeout: 60_000 });
  await doneButton.click();
  await expect(page.getByTestId("upload-modal")).toBeHidden();

  const docs = await queryRaw(
    `SELECT id FROM documents WHERE file_name = $1 AND deleted_at IS NULL`,
    [FIXTURE_NAME],
  );
  const documentId = (docs[0] as { id: string }).id;

  // ── Open the summary ───────────────────────────────────────────────────
  const card = page.getByTestId(`library-doc-${documentId}`);
  await card.click();
  const openSummaryLink = page.getByRole("link", { name: "Open summary" });
  await expect(openSummaryLink).toBeVisible();
  await openSummaryLink.click();
  await expect(page.getByTestId("summary-editor-content")).toBeVisible();

  // ── Highlight the seeded paragraph and ask for a rewrite ──────────────
  const editable = page.getByTestId("summary-editor-content").locator('[contenteditable="true"]');
  await editable.click({ clickCount: 3 }); // triple-click selects the paragraph
  await page.getByTestId("summary-editor-ask-input").fill("make this shorter");
  await page.getByRole("button", { name: "Ask" }).click();

  // ── The scripted suggestion appears; keep it ───────────────────────────
  await expect(page.getByText(SCRIPTED_SUMMARY_EDIT)).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Keep it" }).click();
  await expect(page.getByText(SCRIPTED_SUMMARY_EDIT)).toBeHidden();
  await expect(editable).toContainText(SCRIPTED_SUMMARY_EDIT);

  // ── History records the kept edit and can restore the original ────────
  await page.getByRole("button", { name: "History" }).click();
  await expect(page.getByText("AI edit kept")).toBeVisible();
  await expect(page.getByText("Created")).toBeVisible();
  const restoreButtons = page.getByRole("button", { name: "Bring this back" });
  await restoreButtons.last().click(); // oldest entry = "Created" = the original text
  await expect(editable).not.toContainText(SCRIPTED_SUMMARY_EDIT);

  // ── Sources tab lists the primary document with no remove control ─────
  await page.getByRole("button", { name: "Sources" }).click();
  await expect(page.getByText(FIXTURE_NAME)).toBeVisible();
  await expect(page.getByRole("button", { name: `Remove ${FIXTURE_NAME}` })).toHaveCount(0);

  // ── Deleting the source document cascades to the summary doc ──────────
  const summaryDocRows = await queryRaw(
    `SELECT id FROM summary_docs WHERE primary_document_id = $1`,
    [documentId],
  );
  expect(summaryDocRows).toHaveLength(1);

  await page.goto("/library");
  await card.click();
  const deleteButton = page.getByTestId("library-detail-delete");
  await deleteButton.click();
  await deleteButton.click(); // two-click confirm (useConfirm)
  await expect(card).toBeHidden();

  const summaryDocRowsAfterDelete = await queryRaw(
    `SELECT id FROM summary_docs WHERE primary_document_id = $1`,
    [documentId],
  );
  expect(summaryDocRowsAfterDelete).toHaveLength(0);
});
