/**
 * Journey: upload → SSE → document appears (#387).
 *
 * Drives the REAL streaming pipeline end to end through the UI: pick a
 * fixture PDF in the upload modal (upload-modal testids, #382), start the
 * upload, ride the SSE stream (frontend/src/lib/sse.ts::streamSSE under
 * uploadDocumentStream) to its terminal `done` event, then assert the
 * document appears in the library AND the row exists in Postgres via
 * raw-SQL readback (support/db.ts::query).
 *
 * LLM-dependence (the #387 "known hard part"): the SSE pipeline's happy
 * path is agent-driven — classifier → (summary ∥ concepts) → graph merge —
 * and the documents row is only persisted AFTER those stages, so the
 * journey cannot complete without model responses. The #391 seam covers
 * every one of these agents (they all build via `model_for`); its
 * boot-time half (#392's SAPLING_FUNCTION_HANDLERS autoload, which this
 * PR extends with the upload-pipeline handlers) means the stack MUST be
 * booted with
 *
 *   SAPLING_MODEL_MODE=function \
 *   SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e make e2e-up
 *
 * which swaps deterministic FunctionModel handlers in above the transport
 * (ADR 0019) — every AGENT stage (classifier/summary/concepts/
 * course_summary) is scripted. One pre-existing path sits below the seam:
 * the fire-and-forget RAG post-roll embed (#439) may still attempt a live
 * embedding call; its failures are swallowed, so determinism holds — run
 * verification with a dummy GEMINI_API_KEY so it cannot bill. The spec
 * fail-fasts via /api/health's `model_mode` before uploading so a
 * real-mode stack is caught before the agent stages run. Scripted outputs (category, abstract, concept
 * names) come from backend/agents/function_handlers_e2e.py; asserting
 * their exact values below is what proves the SSE result payload and the
 * persisted row came from the scripted pipeline, not a fallback path.
 *
 * Waiting is event-based only (no waitForTimeout): every wait is an
 * auto-retrying expect() on UI state that a pipeline event flips.
 */
import path from "node:path";

import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import { BACKEND_URL, USER_ACTIVE } from "./support/stack";

const FIXTURE_PDF = path.join(__dirname, "fixtures", "upload-journey.pdf");
const FIXTURE_NAME = "upload-journey.pdf";

// Mirrors backend/agents/function_handlers_e2e.py — the scripted pipeline
// output this journey asserts on. Keep in sync with that module.
const SCRIPTED_CATEGORY = "lecture_notes";
const SCRIPTED_ABSTRACT_SNIPPET = "deterministic fixture content";
const SCRIPTED_CONCEPTS = ["Gradient Descent", "Learning Rate"];

test("upload → SSE → document appears in library and Postgres", async ({
  page,
}) => {
  // Guard: never run this journey against a real-mode stack — the pipeline
  // would dial live Gemini (slow, nondeterministic, billed). /api/health
  // surfaces the #391 seam mode precisely for this fail-fast.
  const health = (await (await fetch(`${BACKEND_URL}/api/health`)).json()) as {
    model_mode?: string;
  };
  expect(
    health.model_mode,
    "Stack is not in deterministic model mode. Reboot it with:\n" +
      "  SAPLING_MODEL_MODE=function " +
      "SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e make e2e-up",
  ).toBe("function");

  // ── Upload through the UI ─────────────────────────────────────────────
  await page.goto("/library");
  await expect(page.getByTestId("app-shell")).toBeVisible();

  // Enabled only once the courses fetch lands (the seeded rich-user-active
  // has enrollments), so this wait also covers the library's initial load.
  const uploadButton = page.getByTestId("library-upload");
  await expect(uploadButton).toBeEnabled();
  await uploadButton.click();

  await expect(page.getByTestId("upload-modal")).toBeVisible();
  await page.getByTestId("upload-modal-file-input").setInputFiles(FIXTURE_PDF);

  const fileRow = page.getByTestId("upload-modal-file-row-0");
  await expect(fileRow).toBeVisible();
  await expect(fileRow).toContainText(FIXTURE_NAME);

  await page.getByTestId("upload-modal-submit").click();

  // ── Ride the SSE stream to completion ─────────────────────────────────
  // The "Done" footer button only replaces "Start upload" once every row
  // left the uploading state — i.e. once streamSSE consumed the terminal
  // `status: done` event and uploadDocumentStream resolved with the
  // persisted document. Event-based wait; generous budget for the OCR +
  // pipeline round trips, but it normally flips in a few seconds.
  const doneButton = page.getByTestId("upload-modal-done");
  await expect(doneButton).toBeVisible({ timeout: 60_000 });

  // The row rendered the orchestrator result from the SSE `result` event:
  // the scripted summary abstract and concept chips — proof the stream
  // delivered the full DocumentProcessingResult, not an error/fallback.
  await expect(fileRow).toContainText(SCRIPTED_ABSTRACT_SNIPPET);
  for (const concept of SCRIPTED_CONCEPTS) {
    await expect(fileRow).toContainText(concept);
  }

  // ── Postgres readback (raw SQL) ───────────────────────────────────────
  const docs = await queryRaw(
    `SELECT id, user_id, offering_id, category, summary
       FROM documents
      WHERE file_name = $1
        AND deleted_at IS NULL`,
    [FIXTURE_NAME],
  );
  expect(docs).toHaveLength(1);
  const doc = docs[0] as {
    id: string;
    user_id: string;
    offering_id: string | null;
    category: string;
    summary: string | null;
  };
  expect(doc.user_id).toBe(USER_ACTIVE);
  expect(doc.category).toBe(SCRIPTED_CATEGORY);
  // Documents key on the offering (0025) — resolve_offering(create=True)
  // must have attached one.
  expect(doc.offering_id).toBeTruthy();
  // `documents.summary` is column-encrypted at rest: present, but the
  // stored value must be ciphertext, never the plaintext abstract.
  expect(doc.summary ?? "").not.toBe("");
  expect(doc.summary ?? "").not.toContain(SCRIPTED_ABSTRACT_SNIPPET);
  expect(doc.summary ?? "").not.toContain("gradient descent");

  // Phase-3 side effect: the scripted concepts were merged into the
  // course knowledge graph (plaintext columns — safe to assert exactly).
  const nodes = await queryRaw(
    `SELECT concept_name
       FROM graph_nodes
      WHERE user_id = $1
        AND concept_name = ANY($2::text[])`,
    [USER_ACTIVE, SCRIPTED_CONCEPTS],
  );
  expect(nodes.map((n) => n.concept_name as string).sort()).toEqual(
    [...SCRIPTED_CONCEPTS].sort(),
  );

  // ── Document appears in the library ───────────────────────────────────
  // Closing via Done triggers the library refetch (onComplete → load()).
  await doneButton.click();
  await expect(page.getByTestId("upload-modal")).toBeHidden();

  const card = page.getByTestId(`library-doc-${doc.id}`);
  await expect(card).toBeVisible();
  await expect(card).toContainText(FIXTURE_NAME);
  // The card renders the decrypted summary — the encryption round-trip
  // (encrypt at persist, decrypt at read) closed correctly.
  await expect(card).toContainText(SCRIPTED_ABSTRACT_SNIPPET);

  // ── Library course filter matches the seeded course (#435) ────────────
  // Regression: GET /api/documents/user/{id} used to return offering_id but
  // never the abstract course_id that Library.tsx filters/labels on, so a
  // freshly uploaded doc could never match a course filter — it always
  // counted as "Uncategorized" no matter which course it was tagged with.
  // Resolve the seeded course from the persisted row itself (offering_id →
  // course_offerings.course_id) rather than assuming which enrolled course
  // the upload modal defaulted to.
  const offeringRows = await queryRaw(
    `SELECT course_id FROM course_offerings WHERE id = $1`,
    [doc.offering_id],
  );
  const courseId = (offeringRows[0] as { course_id: string } | undefined)
    ?.course_id;
  expect(
    courseId,
    "the document's offering must resolve to an abstract course",
  ).toBeTruthy();

  const courseFilter = page.getByTestId(`library-course-filter-${courseId}`);
  await expect(courseFilter).toBeVisible();
  await courseFilter.click();

  // The uploaded doc matches its course's filter — not dropped, not stuck
  // under "Uncategorized".
  await expect(card).toBeVisible();

  const uncategorizedFilter = page.getByTestId(
    "library-course-filter-uncategorized",
  );
  await uncategorizedFilter.click();
  await expect(card).not.toBeVisible();
});
