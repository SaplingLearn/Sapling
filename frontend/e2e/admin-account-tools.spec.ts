/**
 * Admin account tools journey (#804; spec
 * docs/superpowers/specs/2026-11-08-admin-account-tools-design.md).
 *
 * As the seeded admin (rich-user-admin via mintStorageState), open Admin →
 * Users → "Account tools" for the seeded student Sam Second, and drive the two
 * destructive actions through their review step:
 *
 *   - Seed Biology: the review reads the account's CURRENT holdings (Sam's two
 *     baseline enrollments) and nothing has been written yet — the DB still
 *     holds exactly the baseline enrollments. Typing the email arms the final
 *     button; the run toasts, and the DB then holds exactly the four Biology
 *     courses (by catalog code — the seeder creates a missing code, so the
 *     assertion holds whether or not the local catalog carries them) and the
 *     seeded documents are queued for PRIVATE indexing (pending/personal_notes).
 *   - Wipe: the review states the seeded holdings in words ("4 courses, …");
 *     confirming leaves zero enrollments/documents but keeps the account row
 *     and its profile.
 *
 * The copy section shows its not-configured note: no ACCOUNT_SYNC_* vars exist
 * on the E2E stack. Seeding is static content — no LLM call, so the
 * function-mode seam needs no handler here.
 *
 * Isolation: the per-test reset (support/fixtures.ts) restores Sam's baseline;
 * catalog rows the seeder may create (`courses`, `course_offerings`) are in the
 * reset's denylist and are idempotent by code, so re-runs converge.
 */
import fs from "node:fs";
import path from "node:path";

import { expect, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { mintStorageState } from "./support/session";
import { FRONTEND_URL, USER_SECOND } from "./support/stack";

const USER_ADMIN = "rich-user-admin";
const STUDENT_EMAIL = "rich.second@richlocal.test"; // db/seed_local_rich.py
const BASELINE_ENROLLMENTS = ["rich-enr-second-cs101-s26", "rich-enr-second-hist200-f25"];
const BIOLOGY_CODES = ["CAS BI 107", "CAS BI 108", "CAS BI 203", "CAS CH 101"];

// Full-page captures for the PR (in addition to Playwright's own artifacts).
const SCREENS_DIR =
  process.env.E2E_ACCOUNT_TOOLS_SCREENS_DIR?.trim() ||
  "/tmp/claude-1000/-home-andresl-Projects-sapling/e3526248-e177-480e-80d3-4c3c3031cc63/scratchpad/screens";

async function enrollmentIds(userId: string): Promise<string[]> {
  const rows = await queryRaw(
    "SELECT id FROM enrollments WHERE user_id = $1 ORDER BY id",
    [userId],
  );
  return rows.map((r) => String(r.id));
}

async function enrolledCourseCodes(userId: string): Promise<string[]> {
  const rows = await queryRaw(
    `SELECT c.course_code
       FROM enrollments e
       JOIN course_offerings o ON o.id = e.offering_id
       JOIN courses c ON c.id = o.course_id
      WHERE e.user_id = $1
      ORDER BY c.course_code`,
    [userId],
  );
  return rows.map((r) => String(r.course_code));
}

test("admin seeds a student with a major, then wipes it, behind a review step (#804)", async ({
  browser,
}) => {
  fs.mkdirSync(SCREENS_DIR, { recursive: true });

  // Precondition: Sam starts from the seeded baseline (two enrollments).
  expect(await enrollmentIds(USER_SECOND)).toEqual(BASELINE_ENROLLMENTS);

  const adminState = await mintStorageState(USER_ADMIN, "Ada Admin");
  const ctx = await browser.newContext({ storageState: adminState });
  try {
    const page = await ctx.newPage();
    await page.goto(`${FRONTEND_URL}/admin`);

    // Users is the default tab; open Sam's account tools.
    await page.getByTestId(`admin-user-account-tools-${USER_SECOND}`).click();
    const dialog = page.getByTestId("admin-account-tools");
    await expect(dialog).toBeVisible();

    // The environment the buttons write to leads the dialog.
    await expect(page.getByTestId("admin-account-env")).toHaveAttribute("data-env", "local");
    await expect(page.getByTestId("admin-account-env-badge")).toHaveText("LOCAL");

    // No ACCOUNT_SYNC_* config on the E2E stack: no copy buttons, just the note.
    await expect(page.getByTestId("admin-account-copy-unconfigured")).toBeVisible();
    await expect(page.getByTestId("admin-account-copy-push")).toHaveCount(0);
    await expect(page.getByTestId("admin-account-copy-pull")).toHaveCount(0);

    // ── Seed Biology ───────────────────────────────────────────────────────
    await page.getByTestId("admin-account-major").selectOption({ label: "Biology" });
    const majorCourses = page.getByTestId("admin-account-major-courses");
    for (const code of BIOLOGY_CODES) await expect(majorCourses).toContainText(code);
    await expect(page.getByTestId("admin-account-seed")).toHaveText("Seed Biology…");
    await page.screenshot({ path: path.join(SCREENS_DIR, "01-actions.png"), fullPage: true });

    await page.getByTestId("admin-account-seed").click();
    const review = page.getByTestId("admin-account-review");
    await expect(review).toHaveAttribute("data-action", "seed");
    await expect(page.getByTestId("admin-account-review-target-badge")).toHaveText("LOCAL");
    // What will be deleted: Sam's current holdings, in words, with the
    // baseline's course list (two courses).
    const seedDelete = page.getByTestId("admin-account-review-delete-counts");
    await expect(seedDelete).toContainText("2 courses");
    await expect(page.getByTestId("admin-account-review-delete-courses").locator("li")).toHaveCount(2);
    // What replaces it: the Biology pack.
    const addCourses = page.getByTestId("admin-account-review-add-courses");
    for (const code of BIOLOGY_CODES) await expect(addCourses).toContainText(code);

    // The final button stays disarmed until the email is typed.
    const confirm = page.getByTestId("admin-account-review-confirm");
    await expect(confirm).toBeDisabled();
    await expect(confirm).toContainText(/^Delete \d+ items? and seed Biology$/);
    await page.screenshot({ path: path.join(SCREENS_DIR, "02-seed-review.png"), fullPage: true });

    // Opening the review wrote nothing.
    expect(await enrollmentIds(USER_SECOND)).toEqual(BASELINE_ENROLLMENTS);

    // A wrong email keeps it disarmed; the right one (any case) arms it.
    const confirmInput = page.getByTestId("admin-account-confirm-input");
    await confirmInput.fill("someone.else@richlocal.test");
    await expect(confirm).toBeDisabled();
    await confirmInput.fill(STUDENT_EMAIL.toUpperCase());
    await expect(confirm).toBeEnabled();
    await confirm.click();

    await expect(
      page.getByRole("status").filter({ hasText: /Seeded Sam Second with Biology: created \d+ rows/ }),
    ).toBeVisible({ timeout: 30_000 });
    await expect(dialog).toHaveCount(0);

    // DB: exactly the four Biology courses, nothing stacked on the baseline.
    expect(await enrolledCourseCodes(USER_SECOND)).toEqual(BIOLOGY_CODES);
    const baselineLeft = await enrollmentIds(USER_SECOND);
    for (const id of BASELINE_ENROLLMENTS) expect(baselineLeft).not.toContain(id);
    // Seeded documents are queued for PRIVATE indexing.
    const docs = await queryRaw(
      "SELECT index_status, shareability FROM documents WHERE user_id = $1",
      [USER_SECOND],
    );
    expect(docs.length).toBeGreaterThan(0);
    for (const d of docs) {
      expect(d.index_status).toBe("pending");
      expect(d.shareability).toBe("personal_notes");
    }

    // ── Wipe ───────────────────────────────────────────────────────────────
    await page.getByTestId(`admin-user-account-tools-${USER_SECOND}`).click();
    await expect(dialog).toBeVisible();
    await page.getByTestId("admin-account-wipe").click();
    await expect(review).toHaveAttribute("data-action", "wipe");
    // The seeded holdings, in human words, and the four Biology codes.
    const wipeDelete = page.getByTestId("admin-account-review-delete-counts");
    await expect(wipeDelete).toContainText("4 courses");
    await expect(wipeDelete).toContainText(/\d+ documents?/);
    await expect(wipeDelete).toContainText(/\d[\d,]* XP/);
    const wipeCourses = page.getByTestId("admin-account-review-delete-courses");
    for (const code of BIOLOGY_CODES) await expect(wipeCourses).toContainText(code);
    await expect(page.getByTestId("admin-account-review-kept")).toBeVisible();
    await expect(confirm).toBeDisabled();
    await expect(confirm).toContainText(/^Wipe \d+ items$/);
    await page.screenshot({ path: path.join(SCREENS_DIR, "03-wipe-review.png"), fullPage: true });

    // Still nothing written by the review.
    expect(await enrolledCourseCodes(USER_SECOND)).toEqual(BIOLOGY_CODES);

    await page.getByTestId("admin-account-confirm-input").fill(STUDENT_EMAIL);
    await expect(confirm).toBeEnabled();
    await confirm.click();
    await expect(
      page.getByRole("status").filter({ hasText: /Wiped Sam Second's data: removed \d+ rows/ }),
    ).toBeVisible({ timeout: 30_000 });
    await expect(dialog).toHaveCount(0);

    // DB: study data gone, the account and its profile kept.
    expect(await enrollmentIds(USER_SECOND)).toEqual([]);
    const docsLeft = await queryRaw("SELECT id FROM documents WHERE user_id = $1", [USER_SECOND]);
    expect(docsLeft).toHaveLength(0);
    const account = await queryRaw("SELECT id, is_approved FROM users WHERE id = $1", [USER_SECOND]);
    expect(account).toHaveLength(1);
    expect(account[0].is_approved).toBe(true);
    const profile = await queryRaw("SELECT user_id FROM user_profiles WHERE user_id = $1", [USER_SECOND]);
    expect(profile).toHaveLength(1);
  } finally {
    await ctx.close();
  }
});
