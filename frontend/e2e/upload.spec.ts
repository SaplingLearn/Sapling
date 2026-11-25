/**
 * Journey: upload → SSE → document appears (#387).
 *
 * Drives the REAL streaming pipeline end to end through the UI: pick a
 * fixture PDF from the Library's Upload menu, choose its course in the
 * "Where Does This Belong?" dialog (library-upload-* testids, the #717
 * rebuild), ride the SSE stream (frontend/src/lib/sse.ts::streamSSE under
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
 *
 * Also carries the #435 library-course regression coverage: once the
 * uploaded document appears, the journey resolves its course from Postgres
 * and asserts the Library's scope for that course surfaces the document (and
 * "No Course" does not) — the regression being that
 * GET /api/documents/user/{id} never returned course_id, so every upload
 * silently landed under "no course" regardless of its real course.
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

/**
 * Journey (#186): a course added inline from the upload modal must be
 * immediately selectable in the per-file Course dropdown — the whole point
 * of the inline affordance. Before the fix, `courses` was a parent-owned
 * prop refreshed only via onComplete (fired at done/close), so the freshly
 * added course never appeared within the same modal session.
 *
 * The Library's own upload dialog (#717) has no inline add, so the journey
 * opens the modal where it still lives: Calendar's "Import syllabus".
 *
 * Uses the REAL catalog search + enroll routes against the seeded catalog:
 * HIST200 (rich-course-hist200, db/seed_local_rich.py) exists in the
 * catalog but rich-user-active is NOT enrolled in it — exactly the state
 * the inline add exists for. No LLM stage runs (no upload is started), so
 * this journey needs only the stack, not the model seam.
 */
test("a course added inline is immediately selectable for the queued file (#186)", async ({
  page,
}) => {
  await page.goto("/calendar");
  await page.getByTestId("calendar-import-syllabus").click();
  await expect(page.getByTestId("upload-modal")).toBeVisible();

  // Queue a file so a per-file Course dropdown exists to assert on.
  await page.getByTestId("upload-modal-file-input").setInputFiles(FIXTURE_PDF);
  await expect(page.getByTestId("upload-modal-file-row-0")).toBeVisible();

  // Inline-add the unenrolled seeded catalog course through the real flow.
  await page.getByTestId("upload-modal-course-search").fill("HIST200");
  await page
    .getByTestId("upload-modal-course-result-rich-course-hist200")
    .click();

  // The just-added course is selectable in the file row's dropdown NOW —
  // without closing/reopening the modal.
  await page
    .getByTestId("upload-modal-file-row-0")
    .getByRole("button", { name: "Course" })
    .click();
  await expect(
    page.getByRole("option", { name: /HIST200/ }),
  ).toBeVisible();

  // And the enrollment really happened server-side (real route, real DB).
  const enrollments = await queryRaw(
    `SELECT e.id
       FROM enrollments e
       JOIN course_offerings o ON o.id = e.offering_id
      WHERE e.user_id = $1 AND o.course_id = $2`,
    [USER_ACTIVE, "rich-course-hist200"],
  );
  expect(enrollments.length).toBeGreaterThanOrEqual(1);
});

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

  // "Upload Documents" opens the browser's file picker on the hidden input.
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("menuitem", { name: "Upload Documents" }).click();
  await (await chooser).setFiles(FIXTURE_PDF);

  const dialog = page.getByTestId("library-upload-where");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(FIXTURE_NAME);

  // Pick a course (nothing in the filename suggests one), then add it.
  const confirm = page.getByTestId("library-upload-confirm");
  await dialog.getByRole("radio").first().click();
  await expect(confirm).toBeEnabled();
  await confirm.click();

  // ── Ride the SSE stream to completion ─────────────────────────────────
  // The row says "Added to your library" only once streamSSE consumed the
  // terminal `status: done` event and uploadDocumentStream resolved with
  // the persisted document; Done enables once every row has settled.
  // Event-based waits; generous budget for the OCR + pipeline round trips,
  // but it normally flips in a few seconds.
  await expect(dialog).toContainText("Added to your library", { timeout: 60_000 });
  const doneButton = page.getByTestId("library-upload-done");
  await expect(doneButton).toBeEnabled({ timeout: 60_000 });

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
  // Once every file settled, the Library reloaded and moved to the course
  // the upload landed in; Done just closes the dialog.
  await doneButton.click();
  await expect(dialog).toBeHidden();

  const card = page.getByTestId(`library-doc-${doc.id}`);
  await expect(card).toBeVisible();
  await expect(card).toContainText(FIXTURE_NAME);
  // The row's subtitle is the decrypted summary — the encryption round-trip
  // (encrypt at persist, decrypt at read) closed correctly.
  await expect(card).toContainText(SCRIPTED_ABSTRACT_SNIPPET);

  // ── The document sits in its course's scope (#435) ────────────────────
  // Regression: GET /api/documents/user/{id} used to return offering_id but
  // never the abstract course_id the Library scopes on, so a freshly
  // uploaded doc could never match its course — it always counted as having
  // none. Resolve the course from the persisted row itself (offering_id →
  // course_offerings.course_id).
  const courseRows = await queryRaw(
    `SELECT c.id, c.course_name
       FROM course_offerings o
       JOIN courses c ON c.id = o.course_id
      WHERE o.id = $1`,
    [doc.offering_id],
  );
  const course = courseRows[0] as { id: string; course_name: string } | undefined;
  expect(
    course?.id,
    "the document's offering must resolve to an abstract course",
  ).toBeTruthy();

  // The Library is standing in that course, and the document is there.
  const switcher = page.getByTestId("library-course-switcher");
  await expect(switcher).toContainText(course!.course_name);
  await expect(card).toBeVisible();

  // Under "No Course" it is not.
  await switcher.click();
  await page.getByRole("option", { name: /^No Course/ }).click();
  await expect(switcher).toContainText("No Course");
  await expect(card).not.toBeVisible();
});
