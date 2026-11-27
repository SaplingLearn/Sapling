/**
 * Journey: upload → SSE → document appears (#387).
 *
 * Drives the REAL streaming pipeline end to end through the UI: pick a
 * fixture PDF in the Library's uploader (#717: `library-upload` opens the
 * file picker, then the "Where does this belong?" dialog,
 * `library-upload-where`), start the upload, ride the SSE stream (frontend/src/lib/sse.ts::streamSSE under
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
 * The upload modal of #382 (`upload-modal-*`) now opens only from the
 * Calendar's "Import syllabus"; the journeys that test the modal itself (the
 * inline course add, Re-analyze) open it there.
 *
 * Also carries the #435 course-scope regression coverage: once the uploaded
 * document appears, the journey resolves its seeded course from Postgres and
 * asserts scoping the library to that course still surfaces the document (and
 * "No Course" does not) — the regression being that
 * GET /api/documents/user/{id} never returned course_id, so every upload
 * silently landed under "no course" regardless of its real course.
 */
import path from "node:path";

import type { Page } from "@playwright/test";

import { queryRaw, setUserFlag } from "./support/db";
import { expect, loopOffLane, test } from "./support/fixtures";
import { mintStorageState } from "./support/session";
import { BACKEND_URL, FRONTEND_URL, USER_ACTIVE } from "./support/stack";

const FIXTURE_PDF = path.join(__dirname, "fixtures", "upload-journey.pdf");
const FIXTURE_NAME = "upload-journey.pdf";
const FIXTURE_STEM = "upload-journey";

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

/** Open the #382 upload modal. Since the Library's v2 rebuild (#717) it
 * lives behind the Calendar's "Import syllabus"; the Library has its own
 * uploader (`uploadInLibrary`). */
async function openUploadModal(page: Page): Promise<void> {
  await page.goto("/calendar");
  await page.getByRole("button", { name: "Import syllabus" }).click();
  await expect(page.getByTestId("upload-modal")).toBeVisible();
}

/** Upload the fixture through the upload modal; leaves the modal open on its
 * Done footer, the file's row processed. */
async function uploadFixture(page: Page): Promise<void> {
  await openUploadModal(page);
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
  await openUploadModal(page);

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
  await expect(page.getByTestId("library-upload")).toBeEnabled();
  // The Upload button opens a menu whose "Upload files" clicks this hidden
  // picker; setting its files directly is the same change event.
  await page.locator('input[type="file"][accept=".pdf,.pptx,.docx"]').setInputFiles(FIXTURE_PDF);

  const where = page.getByTestId("library-upload-where");
  await expect(where).toBeVisible();
  // v2 names a file without its extension (the format is its own badge).
  await expect(where).toContainText(FIXTURE_STEM);
  // A course must be chosen before "Add to Library" enables: take the
  // suggestion when the dialog made one, else the first enrolled course.
  const courses = where.getByRole("radiogroup", { name: "Course" });
  if ((await courses.getByRole("radio", { checked: true }).count()) === 0) {
    await courses.getByRole("radio").first().click();
  }
  await page.getByTestId("library-upload-confirm").click();

  // ── Ride the SSE stream to completion ─────────────────────────────────
  // The footer reads "Working…" (disabled) while any row is uploading and
  // turns into an enabled "Done" once every row resolved — i.e. once the
  // stream consumed its terminal `status: done` event and
  // uploadDocumentStream resolved with the persisted document.
  await expect(where).toContainText("Added to your library", { timeout: 60_000 });
  const doneButton = where.getByRole("button", { name: "Done" });
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

  // PKG-14b kill-switch drill (spec §11.1 item 3b, §11.6): with the loop off
  // for the uploader (the kill switch, or the learning_loop flag off) the
  // upload hook drafts NO check items (the ingest hook reads the loop gate per
  // uploader). The default lane drafts them; its count is the
  // check-items journeys' business, not this one's.
  if (loopOffLane) {
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
  await doneButton.click();
  await expect(page.getByTestId("library-upload-where")).toBeHidden();

  const card = page.getByTestId(`library-doc-${doc.id}`);
  await expect(card).toBeVisible();
  await expect(card).toContainText(FIXTURE_STEM);
  // Its details dialog renders the decrypted summary and the concepts — the
  // encryption round-trip (encrypt at persist, decrypt at read) closed
  // correctly, and the SSE result carried the scripted pipeline's output.
  await card.getByRole("button", { name: "Details and actions" }).click();
  const details = page.getByTestId("library-doc-menu");
  await expect(details).toContainText(SCRIPTED_ABSTRACT_SNIPPET);
  for (const concept of SCRIPTED_CONCEPTS) {
    await expect(details).toContainText(concept);
  }
  // W8.1: where to go next with it — its concepts on the Tree.
  await expect(details.getByTestId("library-next-tree")).toBeVisible();
  // The dialog closes on a click on its scrim (fixed, the whole viewport).
  await page.mouse.click(5, 5);
  await expect(details).toBeHidden();

  // ── Library course scope matches the seeded course (#435) ─────────────
  // Regression: GET /api/documents/user/{id} used to return offering_id but
  // never the abstract course_id the Library scopes and labels on, so a
  // freshly uploaded doc could never match its course — it always counted as
  // having none, whichever course it was tagged with. Resolve the seeded
  // course from the persisted row itself (offering_id →
  // course_offerings.course_id) rather than assuming which enrolled course
  // the upload dialog defaulted to.
  const offeringRows = await queryRaw(
    `SELECT o.course_id, c.course_code
       FROM course_offerings o
       JOIN courses c ON c.id = o.course_id
      WHERE o.id = $1`,
    [doc.offering_id],
  );
  const course = offeringRows[0] as { course_id: string; course_code: string } | undefined;
  expect(course?.course_id, "the document's offering must resolve to an abstract course").toBeTruthy();

  const switcher = page.getByTestId("library-course-switcher");
  await switcher.click();
  await page.getByRole("option", { name: new RegExp(course!.course_code) }).first().click();
  // The uploaded doc is in its course's scope — not dropped, not stuck
  // under "No Course".
  await expect(card).toBeVisible();

  await switcher.click();
  await page.getByRole("option", { name: /No Course/ }).click();
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
test("with upload_prereq_edges on, an upload writes its prerequisite edge once (A118), and none with the loop off", async ({
  browser,
  page,
}) => {
  // #866 K55/Z42: A118 is a learning-loop amendment, so the edges follow the
  // uploader's loop gate — with the loop off (both off lanes) the upload is the
  // pre-loop upload and writes no edge, whatever this flag says. Both halves
  // run: the off lanes pin that the flag alone writes nothing.
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
  if (loopOffLane) {
    // The loop is off for the uploader: the flag on, still no edge (K55) —
    // between concepts the upload did write, so the empty answer is not vacuous.
    const nodes = (await queryRaw(
      "SELECT DISTINCT concept_name FROM graph_nodes WHERE user_id = $1 AND concept_name = ANY($2::text[])",
      [USER_ACTIVE, SCRIPTED_CONCEPTS],
    )) as { concept_name: string }[];
    expect(nodes.map((n) => n.concept_name).sort()).toEqual([...SCRIPTED_CONCEPTS].sort());
    expect(first).toEqual([]);
    return;
  }
  expect(first.map((e) => [e.source, e.target])).toEqual(SCRIPTED_PREREQUISITES);

  // Re-analyze. The second documents row is persisted AFTER the graph phase
  // (nodes, then edges) of that run, so once it exists the edge write has run.
  await page.getByTestId("upload-modal-file-reanalyze-0").click();
  await expect.poll(uploadedFixtureCount, { timeout: 60_000 }).toBe(2);
  await expect(page.getByTestId("upload-modal-done")).toBeVisible({ timeout: 60_000 });
  expect(await scriptedPrerequisiteEdges()).toEqual(first);
});

/**
 * PR #866 Z14 / Z66: with `db_user_scope=enforce` for the uploader (#115),
 * every PostgREST call of the upload request goes out as the student, under
 * the real RLS policies and grants. The drafting that the upload's post-roll
 * runs reads and writes the loop's service-only tables (check_items and its
 * bookkeeping, spec §13 A148) and the two drafting-status columns of
 * `documents` the student may not UPDATE, so it must run as the service role.
 * Before the fix the drafting reads 401/403'd as the student: no item was
 * drafted and the status never reached `done`. The hermetic tests
 * (tests/test_check_item_drafting_scope.py) mock the identity; this is the one
 * check of the whole chain against the real grants.
 */
test("an upload by a student under db_user_scope=enforce drafts its check items (#866 Z14, Z66)", async ({
  page,
}) => {
  test.skip(loopOffLane, "loop path: drafting runs only with the loop on for the uploader");
  await expectFunctionMode();
  await setUserFlag("db_user_scope", USER_ACTIVE, "enforce");

  await uploadFixture(page);
  const docs = (await queryRaw(
    "SELECT id FROM documents WHERE file_name = $1 AND deleted_at IS NULL",
    [FIXTURE_NAME],
  )) as { id: string }[];
  expect(docs).toHaveLength(1);
  const docId = docs[0].id;

  // The drafting ran to its end as the service role: the row records `done`
  // and the document's concepts have items drafted from it.
  const drafting = async () => {
    const [row] = (await queryRaw(
      `SELECT d.check_items_status AS status,
              (SELECT count(*)::int FROM check_items i
                WHERE d.id = ANY(i.source_document_ids)) AS items
         FROM documents d
        WHERE d.id = $1`,
      [docId],
    )) as { status: string | null; items: number }[];
    return { status: row.status, drafted: row.items > 0 };
  };
  await expect.poll(drafting, { timeout: 30_000 }).toEqual({ status: "done", drafted: true });
});
