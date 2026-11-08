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
 *
 * Also carries the #435 library-course-filter regression coverage: once the
 * uploaded document appears, the journey resolves its seeded course from
 * Postgres and asserts filtering the library by that course still surfaces
 * the document (and "Uncategorized" does not) — the regression being that
 * GET /api/documents/user/{id} never returned course_id, so every upload
 * silently miscategorized as "Uncategorized" regardless of its real course.
 */
import path from "node:path";

import type { Page } from "@playwright/test";

import { queryRaw } from "./support/db";
import { expect, killSwitchLane, test } from "./support/fixtures";
import { mintStorageState } from "./support/session";
import { BACKEND_URL, FRONTEND_URL, USER_ACTIVE } from "./support/stack";

const FIXTURE_PDF = path.join(__dirname, "fixtures", "upload-journey.pdf");
const FIXTURE_NAME = "upload-journey.pdf";

// Mirrors backend/agents/function_handlers_e2e.py — the scripted pipeline
// output this journey asserts on. Keep in sync with that module.
const SCRIPTED_CATEGORY = "lecture_notes";
const SCRIPTED_ABSTRACT_SNIPPET = "deterministic fixture content";
const SCRIPTED_CONCEPTS = ["Gradient Descent", "Learning Rate"];
// E2E_DOC_PREREQUISITES (learning-loop spec §13 A118): [prerequisite,
// dependent]. Only an uploader with the upload_prereq_edges flag on gets the
// prerequisite extraction (which reads them) and the edge write — off in this
// lane unless a journey turns it on.
const SCRIPTED_PREREQUISITES = [["Gradient Descent", "Learning Rate"]];

const USER_ADMIN = "rich-user-admin"; // seeded with the admin role

/**
 * USER_ACTIVE's prerequisite edges between the scripted concepts, by name.
 * `source` is the prerequisite and `target` the dependent —
 * learning.params.EDGE_PREREQ_SOURCE_IS_PREREQ, the direction propagation and
 * the planner read (spec §3.1).
 */
async function scriptedPrerequisiteEdges(): Promise<
  { id: string; source: string; target: string }[]
> {
  return (await queryRaw(
    `SELECT e.id, s.concept_name AS source, t.concept_name AS target
       FROM graph_edges e
       JOIN graph_nodes s ON s.id = e.source_node_id
       JOIN graph_nodes t ON t.id = e.target_node_id
      WHERE e.user_id = $1
        AND e.relationship_type = 'prerequisite'
        AND s.concept_name = ANY($2::text[])
        AND t.concept_name = ANY($2::text[])
      ORDER BY e.id`,
    [USER_ACTIVE, SCRIPTED_CONCEPTS],
  )) as { id: string; source: string; target: string }[];
}

async function uploadedFixtureCount(): Promise<number> {
  const rows = (await queryRaw(
    "SELECT count(*)::int AS n FROM documents WHERE file_name = $1 AND deleted_at IS NULL",
    [FIXTURE_NAME],
  )) as { n: number }[];
  return rows[0].n;
}

/** Fail fast unless the stack runs the deterministic model seam (#391). */
async function expectFunctionMode(): Promise<void> {
  const health = (await (await fetch(`${BACKEND_URL}/api/health`)).json()) as {
    model_mode?: string;
  };
  expect(
    health.model_mode,
    "Stack is not in deterministic model mode. Reboot it with:\n" +
      "  SAPLING_MODEL_MODE=function " +
      "SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e make e2e-up",
  ).toBe("function");
}

/** Upload the fixture through the library's upload modal; leaves the modal
 * open on its Done footer, the file's row processed. */
async function uploadFixture(page: Page): Promise<void> {
  await page.goto("/library");
  const uploadButton = page.getByTestId("library-upload");
  await expect(uploadButton).toBeEnabled();
  await uploadButton.click();
  await expect(page.getByTestId("upload-modal")).toBeVisible();
  await page.getByTestId("upload-modal-file-input").setInputFiles(FIXTURE_PDF);
  await expect(page.getByTestId("upload-modal-file-row-0")).toBeVisible();
  await page.getByTestId("upload-modal-submit").click();
  await expect(page.getByTestId("upload-modal-done")).toBeVisible({ timeout: 60_000 });
}

/**
 * Journey (#186): a course added inline from the upload modal must be
 * immediately selectable in the per-file Course dropdown — the whole point
 * of the inline affordance. Before the fix, `courses` was a parent-owned
 * prop refreshed only via onComplete (fired at done/close), so the freshly
 * added course never appeared within the same modal session.
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
  await page.goto("/library");
  const uploadButton = page.getByTestId("library-upload");
  await expect(uploadButton).toBeEnabled();
  await uploadButton.click();
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
  // would dial a live model (slow, nondeterministic, billed). /api/health
  // surfaces the #391 seam mode precisely for this fail-fast.
  await expectFunctionMode();

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

  // PKG-14b kill-switch drill (spec §11.1 item 3b, §11.6): under the kill
  // switch the upload hook drafts NO check items (the ingest hook is gated on
  // LEARNING_LOOP_ENABLED). The default lane drafts them; its count is the
  // check-items journeys' business, not this one's.
  if (killSwitchLane) {
    const drafted = (await queryRaw(
      "SELECT count(*)::int AS n FROM check_items WHERE $1 = ANY(source_document_ids)",
      [doc.id],
    )) as { n: number }[];
    expect(drafted[0].n).toBe(0);
  }

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
  // A118: upload_prereq_edges is off here (no flag row), so the upload ran
  // the pre-A118 extraction (the scripted relation is ignored) and wrote
  // nodes only. The flag-on journey is at the end of the file.
  expect(await scriptedPrerequisiteEdges()).toEqual([]);

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

/**
 * Journey (learning-loop spec §13 A118): with upload_prereq_edges on for the
 * uploader, the upload writes the scripted prerequisite relation as ONE
 * `prerequisite` edge, oriented source = prerequisite; Re-analyze — the same
 * file under a fresh request id, so the whole pipeline re-runs — re-derives
 * that edge and writes nothing (the same row, the same id). Before A118 an
 * upload wrote nodes only, so every prerequisite consumer of the learning
 * loop (propagation, bands, the planner's fringe) was inert on upload-built
 * graphs.
 */
test("with upload_prereq_edges on, an upload writes its prerequisite edge once (A118)", async ({
  browser,
  page,
}) => {
  await expectFunctionMode();

  // Turn the flag on for this student through the API the /admin tab uses.
  const adminState = await mintStorageState(USER_ADMIN, "Ada Admin");
  const adminCtx = await browser.newContext({ storageState: adminState });
  const res = await adminCtx.request.put(
    `${FRONTEND_URL}/api/admin/flags/upload_prereq_edges/targets`,
    { data: { target_type: "user", target_id: USER_ACTIVE, variant: "on" } },
  );
  expect(res.ok()).toBeTruthy();
  await adminCtx.close();

  await uploadFixture(page);
  const first = await scriptedPrerequisiteEdges();
  expect(first.map((e) => [e.source, e.target])).toEqual(SCRIPTED_PREREQUISITES);

  // Re-analyze. The second documents row is persisted AFTER the graph phase
  // (nodes, then edges) of that run, so once it exists the edge write has run.
  await page.getByTestId("upload-modal-file-reanalyze-0").click();
  await expect.poll(uploadedFixtureCount, { timeout: 60_000 }).toBe(2);
  await expect(page.getByTestId("upload-modal-done")).toBeVisible({ timeout: 60_000 });
  expect(await scriptedPrerequisiteEdges()).toEqual(first);
});
