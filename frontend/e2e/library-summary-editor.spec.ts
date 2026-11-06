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
  // The rewrite replaces the whole selected paragraph, so the kept text
  // becomes the real (permanently visible) paragraph content — the same
  // string the suggestion card showed as its preview. Asserting THAT text
  // disappears is unsatisfiable; assert the card's own controls are gone
  // instead, which is what actually proves the pending suggestion resolved.
  await expect(page.getByRole("button", { name: "Keep it" })).toBeHidden();
  await expect(editable).toContainText(SCRIPTED_SUMMARY_EDIT);

  // ── History records the kept edit and can restore the original ────────
  await page.getByRole("button", { name: "History" }).click();
  await expect(page.getByText("AI edit kept")).toBeVisible();
  await expect(page.getByText("Created")).toBeVisible();
  // The button reads "Bring this back", but each one carries an aria-label
  // ("Restore version from <date>") so screen-reader users can tell the
  // repeated buttons apart — and an aria-label REPLACES the visible text as
  // the accessible name getByRole matches on. Locate by that name, not the
  // label the eye sees, or this never resolves.
  const restoreButtons = page.getByRole("button", { name: /^Restore version from / });
  await restoreButtons.last().click(); // list is created_at.desc, so last = oldest = "Created"
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

test("circling a PDF source and asking adds it to the summary", async ({ page }) => {
  const health = (await (await fetch(`${BACKEND_URL}/api/health`)).json()) as { model_mode?: string };
  expect(
    health.model_mode,
    "Stack is not in deterministic model mode. Reboot it with:\n" +
      "  SAPLING_MODEL_MODE=function " +
      "SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e make e2e-up",
  ).toBe("function");

  // ── Upload, same as the journey above ─────────────────────────────────
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

  await page.getByTestId(`library-doc-${documentId}`).click();
  await page.getByRole("link", { name: "Open summary" }).click();
  await expect(page.getByTestId("summary-editor-content")).toBeVisible();

  // ── Open the source as a split pane and circle a region ───────────────
  await page.getByRole("button", { name: FIXTURE_NAME }).click();
  const page0 = page.getByTestId("summary-editor-source-page-0");
  await expect(page0).toBeVisible();
  const box = await page0.boundingBox();
  if (!box) throw new Error("source page canvas has no bounding box");
  // A deliberate rectangular-ish lasso well over the MIN_LASSO_SPAN guard
  // (SourceViewer.tsx: 8px of travel) so it registers as a real crop, not
  // a stray click.
  await page.mouse.move(box.x + 20, box.y + 20);
  await page.mouse.down();
  await page.mouse.move(box.x + 120, box.y + 20);
  await page.mouse.move(box.x + 120, box.y + 120);
  await page.mouse.move(box.x + 20, box.y + 120);
  await page.mouse.up();

  await expect(page.getByText("Circled region attached")).toBeVisible();

  // ── Ask with the reference attached; it goes through the whole-doc path ──
  await page.getByTestId("summary-editor-ask-input").fill("add this diagram's caption");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByText(SCRIPTED_SUMMARY_EDIT)).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Keep it" }).click();
  await expect(page.getByRole("button", { name: "Keep it" })).toBeHidden();

  const editable = page.getByTestId("summary-editor-content").locator('[contenteditable="true"]');
  await expect(editable).toContainText(SCRIPTED_SUMMARY_EDIT);

  // ── Closing the source tab returns to the plain summary view ──────────
  await page.getByRole("button", { name: FIXTURE_NAME }).click();
  await expect(page.getByTestId("summary-editor-source-pane")).toBeHidden();
});
