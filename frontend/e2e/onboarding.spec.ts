/** The six approved Pen onboarding frames, backed by real catalog, profile,
 * upload and learning routes. Only failure-state requests are intercepted.
 * The upload journey requires deterministic FunctionModels, exactly as
 * upload.spec.ts; no successful API response or student state is fabricated.
 */
import fs from "node:fs/promises";
import path from "node:path";
import type { Browser, Page, Request } from "@playwright/test";
import { queryRaw } from "./support/db";
import { decryptTexts } from "./support/decrypt";
import { expect, killSwitchLane, test } from "./support/fixtures";
import { mintStorageState } from "./support/session";
import { BACKEND_URL, FRONTEND_URL, USER_NEW } from "./support/stack";

const FIXTURE_PDF = path.join(__dirname, "fixtures", "upload-journey.pdf");
const EVIDENCE_DIR = process.env.ONBOARDING_EVIDENCE_DIR?.trim();
const OBJECTIVE = "Explain how gradient descent uses the learning rate.";
const HEADINGS = [
  "Welcome to Sapling.", "What are you studying?", "Connect your courses.",
  "Bring your course materials.", "What would you like to work toward?", "Ready for your first check-in.",
];
type Course = { id: string; course_code: string; course_name: string };
type SavedSession = {
  id: string;
  course_id: string;
  loop_state: { goal?: { text_encrypted: string; target_node_ids: string[] }; goal_version?: number };
};

async function signIn(browser: Browser, phone = false) {
  const context = await browser.newContext({
    storageState: await mintStorageState(USER_NEW, "Newt Newman"),
    viewport: phone ? { width: 320, height: 740 } : { width: 1440, height: 960 },
    ...(phone ? { isMobile: true, hasTouch: true } : {}),
  });
  const page = await context.newPage();
  await page.addInitScript(() => {
    localStorage.setItem("sapling_disclaimer_ack", "true");
    localStorage.setItem("sapling_last_feedback", String(Date.now()));
    localStorage.setItem("sapling_last_session_feedback", String(Date.now()));
  });
  return { context, page };
}

function observeWrites(page: Page) {
  const profiles: Request[] = [];
  const learning: Request[] = [];
  const starts: Request[] = [];
  page.on("request", request => {
    const pathname = new URL(request.url()).pathname;
    if (request.method() === "POST" && pathname === "/api/onboarding/profile") profiles.push(request);
    if (pathname.startsWith("/api/learn/loop/")) learning.push(request);
    if (request.method() === "POST" && pathname === "/api/learn/loop/start-session") starts.push(request);
  });
  return { profiles, learning, starts };
}

async function step(page: Page, value: number) {
  await expect(page.getByTestId("onboarding-gate")).toHaveAttribute("data-step", String(value));
  await expect(page.getByRole("heading", { level: 1, name: HEADINGS[value - 1], exact: true })).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "Onboarding progress" })).toHaveAttribute("aria-valuenow", String(value));
}

async function evidence(page: Page, name: string) {
  if (!EVIDENCE_DIR) return;
  await fs.mkdir(EVIDENCE_DIR, { recursive: true });
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await page.getByRole("heading", { level: 1 }).focus();
  await page.screenshot({ path: path.join(EVIDENCE_DIR, `${name}.png`), animations: "disabled" });
}

async function noHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  const primary = page.getByTestId("onboarding-continue");
  await primary.scrollIntoViewIfNeeded();
  await expect(primary).toBeInViewport();
}

async function names(page: Page) {
  await page.getByTestId("onboarding-first-name").fill("Alex");
  await page.getByTestId("onboarding-last-name").fill("Rivera");
}

async function academics(page: Page) {
  await page.getByTestId("onboarding-year").selectOption("sophomore");
  await page.getByTestId("onboarding-chip-input-majors").fill("Computer Science");
  await page.getByTestId("onboarding-chip-input-minors").fill("Mathematics");
}

async function selectRealCourse(page: Page, code = "CS101"): Promise<Course> {
  const response = page.waitForResponse(value => {
    const url = new URL(value.url());
    return url.pathname === "/api/onboarding/courses" && url.searchParams.get("q") === code;
  });
  await page.getByTestId("onboarding-course-search").fill(code);
  const result = await response;
  expect(result.ok()).toBe(true);
  const catalog = await result.json() as { courses: Course[] };
  // Catalog codes can exist in more than one seeded school. Use the real
  // deduplicated result, and assert this same course all the way into learning.
  const course = catalog.courses.find(value => value.course_code === code);
  expect(course, `the real seeded catalog must offer ${code}`).toBeTruthy();
  const choice = page.getByTestId(`onboarding-course-result-${course!.id}`);
  await expect(choice).toBeAttached();
  await choice.locator("..").click(); // the visible label owns the native checkbox
  await expect(choice).toBeChecked();
  return course!;
}

async function persistedProfile(courseId: string) {
  const rows = await queryRaw(
    `SELECT u.onboarding_completed, p.name, p.first_name, p.last_name, p.year, p.majors, p.minors
       FROM users u JOIN user_profiles p ON p.user_id = u.id WHERE u.id = $1`, [USER_NEW],
  );
  expect(rows).toHaveLength(1);
  const profile = rows[0];
  expect(profile).toMatchObject({ onboarding_completed: true, year: "sophomore", majors: ["Computer Science"], minors: ["Mathematics"] });
  const encrypted = [profile.name, profile.first_name, profile.last_name] as string[];
  expect(encrypted).not.toEqual(["Alex Rivera", "Alex", "Rivera"]);
  expect(await decryptTexts(encrypted)).toEqual(["Alex Rivera", "Alex", "Rivera"]);
  const enrollment = await queryRaw(
    `SELECT e.id FROM enrollments e JOIN course_offerings o ON o.id = e.offering_id
      WHERE e.user_id = $1 AND o.course_id = $2`, [USER_NEW, courseId],
  );
  expect(enrollment).toHaveLength(1);
}

async function sessions(): Promise<SavedSession[]> {
  return await queryRaw(
    `SELECT s.id, o.course_id, s.loop_state FROM sessions s
       JOIN course_offerings o ON o.id = s.offering_id WHERE s.user_id = $1 ORDER BY s.id`, [USER_NEW],
  ) as SavedSession[];
}

test("desktop onboarding: six Pen screens → real upload → confirmed goal → one scoped check-in", async ({ browser }) => {
  test.skip(killSwitchLane, "goal-scoped check-in requires the default learning-loop lane");
  test.setTimeout(180_000);
  const health = await (await fetch(`${BACKEND_URL}/api/health`)).json() as { model_mode?: string };
  expect(health.model_mode, "Upload requires SAPLING_MODEL_MODE=function and agents.function_handlers_e2e, as upload.spec.ts").toBe("function");
  const { context, page } = await signIn(browser);
  const writes = observeWrites(page);
  try {
    await page.goto(`${FRONTEND_URL}/onboarding`);
    await step(page, 1);
    await expect(page.getByTestId("onboarding-back")).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0); // standalone native frames
    await names(page);
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    const progress = await page.getByRole("progressbar", { name: "Onboarding progress" }).boundingBox();
    const title = await page.getByRole("heading", { level: 1 }).boundingBox();
    const primary = await page.getByTestId("onboarding-continue").boundingBox();
    // Native Pen canvas at 1440×960; tolerate subpixel font/viewport rounding.
    for (const [actual, expected] of [[progress?.x, 440], [progress?.y, 110], [progress?.width, 560], [title?.y, 202], [primary?.x, 440], [primary?.y, 832], [primary?.width, 560], [primary?.height, 52]]) {
      expect(actual).toBeDefined();
      expect(Math.abs(actual! - expected!)).toBeLessThanOrEqual(1.5);
    }
    const type = await page.getByRole("heading", { level: 1 }).evaluate(element => {
      const css = getComputedStyle(element);
      return { family: css.fontFamily.toLowerCase(), size: css.fontSize, weight: css.fontWeight };
    });
    expect(type.family).toContain("aleo");
    expect(type).toMatchObject({ size: "40px", weight: "600" });
    await evidence(page, "01-profile-desktop");
    await page.getByTestId("onboarding-continue").click();
    await step(page, 2);
    await academics(page);
    await page.getByTestId("onboarding-back").click();
    await page.reload();
    await step(page, 1);
    await expect(page.getByTestId("onboarding-first-name")).toHaveValue("Alex");
    await expect(page.getByTestId("onboarding-last-name")).toHaveValue("Rivera");
    await page.getByTestId("onboarding-continue").click();
    await step(page, 2);
    await expect(page.getByTestId("onboarding-year")).toHaveValue("sophomore");
    await expect(page.getByTestId("onboarding-chip-input-majors")).toHaveValue("Computer Science");
    await evidence(page, "02-academics-desktop");
    await page.getByTestId("onboarding-continue").click();
    await step(page, 3);
    const course = await selectRealCourse(page);
    await evidence(page, "03-courses-desktop");
    await page.reload();
    await step(page, 3);
    await expect(page.getByTestId("onboarding-course-remove-CS101")).toBeVisible();
    expect(writes.profiles).toHaveLength(0);
    const save = page.waitForResponse(response => new URL(response.url()).pathname === "/api/onboarding/profile" && response.request().method() === "POST");
    await page.getByTestId("onboarding-continue").click();
    expect((await save).ok()).toBe(true);
    await step(page, 4);
    expect(writes.profiles).toHaveLength(1);
    expect(writes.profiles[0].postDataJSON()).toMatchObject({ user_id: USER_NEW, first_name: "Alex", last_name: "Rivera", year: "sophomore", course_ids: [course.id] });
    await persistedProfile(course.id);

    // Refresh and Back after the required save cannot silently resubmit it.
    await page.reload();
    await step(page, 4);
    await page.getByTestId("onboarding-back").click();
    await step(page, 3);
    await page.getByTestId("onboarding-continue").click();
    await step(page, 4);
    expect(writes.profiles).toHaveLength(1);
    await page.getByRole("button", { name: "Choose files", exact: true }).click();
    await page.getByTestId("upload-modal-file-input").setInputFiles(FIXTURE_PDF);
    const file = page.getByTestId("upload-modal-file-row-0");
    await expect(file.getByRole("button", { name: "Course", exact: true })).toContainText("CS101");
    await page.getByTestId("upload-modal-submit").click();
    await expect(file).toHaveAttribute("data-status", "processed", { timeout: 60_000 });
    await expect(file).toContainText("Gradient Descent");
    await page.getByTestId("upload-modal-done").click();
    await expect(page.getByTestId("upload-modal")).toBeHidden();
    await expect(page.getByTestId("onboarding-gate")).toContainText("upload-journey.pdf");
    const documents = await queryRaw(
      `SELECT d.id, d.category, o.course_id FROM documents d JOIN course_offerings o ON o.id = d.offering_id
        WHERE d.user_id = $1 AND d.file_name = $2 AND d.deleted_at IS NULL`, [USER_NEW, "upload-journey.pdf"],
    );
    expect(documents).toHaveLength(1);
    expect(documents[0]).toMatchObject({ category: "lecture_notes", course_id: course.id });
    await evidence(page, "04-materials-desktop");
    await page.getByTestId("onboarding-continue").click();
    await step(page, 5);
    await expect(page.getByTestId("onboarding-goal-course")).toHaveValue(course.id);
    await page.getByTestId("onboarding-goal-concept-scope").check();
    const concepts = await queryRaw(
      `SELECT id FROM graph_nodes WHERE user_id = $1 AND course_id = $2 AND concept_name = $3`,
      [USER_NEW, course.id, "Gradient Descent"],
    );
    expect(concepts).toHaveLength(1);
    const targetId = concepts[0].id as string;
    await page.getByTestId(`onboarding-target-${targetId}`).check();
    await page.getByTestId("onboarding-objective").fill(OBJECTIVE);
    await page.getByRole("button", { name: "Edit concepts →", exact: true }).click();
    await evidence(page, "05-goal-desktop");
    await page.getByTestId("onboarding-continue").click();
    await step(page, 6);
    await page.reload();
    await step(page, 6);
    await expect(page.getByTestId("onboarding-gate")).toContainText(OBJECTIVE);
    await expect(page.getByTestId("onboarding-gate")).toContainText("Gradient Descent");
    await page.getByTestId("onboarding-back").click();
    await step(page, 5);
    await expect(page.getByTestId("onboarding-objective")).toHaveValue(OBJECTIVE);
    await page.getByRole("button", { name: "Edit concepts →", exact: true }).click();
    await expect(page.getByTestId(`onboarding-target-${targetId}`)).toBeChecked();
    await page.getByRole("button", { name: "Edit concepts →", exact: true }).click();
    await page.getByTestId("onboarding-continue").click();
    await step(page, 6);
    await evidence(page, "06-review-desktop");
    expect(writes.profiles).toHaveLength(1);
    expect(writes.learning).toHaveLength(0);
    expect(await sessions()).toHaveLength(0);

    // This explicit review action is the first permission to create learning
    // state. The goal travels in the initial start, before the first probe.
    await page.getByTestId("onboarding-continue").dblclick();
    await expect(page).toHaveURL(/\/learn\?/);
    const phase = page.getByTestId("app-shell").getByTestId("loop-phase");
    await expect(phase).toHaveAttribute("data-session-id", /\S+/, { timeout: 30_000 });
    expect(writes.starts).toHaveLength(1);
    expect(writes.starts[0].postDataJSON()).toMatchObject({ user_id: USER_NEW, course_id: course.id, goal: { text: OBJECTIVE, target_node_ids: [targetId] } });
    await expect.poll(async () => (await sessions()).length).toBe(1);
    const [session] = await sessions();
    expect(session.id).toBe(await phase.getAttribute("data-session-id"));
    expect(session.course_id).toBe(course.id);
    expect(session.loop_state.goal?.target_node_ids).toEqual([targetId]);
    expect(session.loop_state.goal_version).toBeGreaterThan(0);
    expect(JSON.stringify(session.loop_state)).not.toContain(OBJECTIVE);
    expect(await decryptTexts([session.loop_state.goal!.text_encrypted])).toEqual([OBJECTIVE]);
    await expect(page.getByTestId("loop-goal-summary")).toContainText(OBJECTIVE);
    const sidebar = page.getByRole("complementary", { name: "Primary navigation" });
    const selectedLearn = page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Learn", exact: true });
    await expect(selectedLearn).toHaveAttribute("aria-current", "page");
    const sidebarBox = await sidebar.boundingBox();
    const wordmarkBox = await sidebar.getByRole("link", { name: "Sapling home" }).boundingBox();
    const selectedBox = await selectedLearn.boundingBox();
    for (const [actual, expected] of [[sidebarBox?.x, 0], [sidebarBox?.width, 216], [sidebarBox?.height, 960], [wordmarkBox?.x, 26], [wordmarkBox?.y, 26], [wordmarkBox?.width, 150], [wordmarkBox?.height, 44.55], [selectedBox?.x, 16], [selectedBox?.y, 190], [selectedBox?.width, 184], [selectedBox?.height, 46]]) {
      expect(actual).toBeDefined();
      expect(Math.abs(actual! - expected!)).toBeLessThanOrEqual(1.5);
    }
    await expect(sidebar).toHaveCSS("background-color", "rgb(229, 235, 221)");
    await expect(selectedLearn).toHaveCSS("background-color", "rgb(247, 244, 233)");
    await evidence(page, "07-check-in-sidebar-desktop");
    await page.reload();
    await expect(phase).toHaveAttribute("data-session-id", session.id, { timeout: 30_000 });
    expect(writes.starts).toHaveLength(1);
    expect((await sessions()).map(value => value.id)).toEqual([session.id]);
  } finally { await context.close(); }
});

test("320px onboarding keeps drafts and recovers catalog/profile failures without starting learning", async ({ browser }) => {
  test.setTimeout(120_000);
  const { context, page } = await signIn(browser, true);
  const writes = observeWrites(page);
  let catalogFails = true;
  await page.route("**/api/onboarding/courses**", route => catalogFails
    ? route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Catalog temporarily unavailable" }) })
    : route.continue());
  try {
    await page.goto(`${FRONTEND_URL}/onboarding`);
    await step(page, 1);
    await page.getByTestId("onboarding-first-name").fill("");
    await expect(page.getByTestId("onboarding-continue")).toBeDisabled();
    await names(page);
    await noHorizontalOverflow(page);
    await page.getByTestId("onboarding-continue").click();
    await step(page, 2);
    await academics(page);
    await noHorizontalOverflow(page);
    await page.getByTestId("onboarding-continue").click();
    await step(page, 3);
    const catalogError = page.getByRole("alert").filter({ hasText: /couldn't search the catalog/i });
    await expect(catalogError).toBeVisible();
    await expect(page.getByTestId("onboarding-continue")).toBeDisabled();
    await noHorizontalOverflow(page);
    catalogFails = false;
    await catalogError.getByRole("button", { name: "Retry", exact: true }).click();
    const course = await selectRealCourse(page);
    await page.route("**/api/onboarding/profile", route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Profile temporarily unavailable" }) }));
    await page.getByTestId("onboarding-continue").click();
    await expect(page.getByTestId("onboarding-save-error")).toContainText("Your choices are kept.");
    await expect(page.getByTestId("onboarding-gate")).toHaveAttribute("data-step", "3");
    const [unsaved] = await queryRaw("SELECT onboarding_completed FROM users WHERE id = $1", [USER_NEW]);
    expect(unsaved.onboarding_completed).toBe(false);
    await page.unroute("**/api/onboarding/profile");
    await page.reload();
    await step(page, 3);
    await expect(page.getByTestId("onboarding-course-remove-CS101")).toBeVisible();
    const save = page.waitForResponse(response => new URL(response.url()).pathname === "/api/onboarding/profile" && response.request().method() === "POST");
    await page.getByTestId("onboarding-continue").click();
    expect((await save).ok()).toBe(true);
    await step(page, 4);
    await persistedProfile(course.id);
    expect(writes.profiles).toHaveLength(2); // one refused write, one real success
    await page.reload();
    await step(page, 4);
    await noHorizontalOverflow(page);
    await page.getByTestId("onboarding-skip-materials").click();
    await step(page, 5);
    await expect(page.getByTestId("onboarding-goal-course")).toHaveValue(course.id);
    await expect(page.getByTestId("onboarding-goal-course-scope")).toBeChecked();
    await noHorizontalOverflow(page);
    await page.getByTestId("onboarding-continue").click();
    await step(page, 6);
    await noHorizontalOverflow(page);
    await expect(page.getByTestId("onboarding-gate")).toContainText("Explore the course.");
    await evidence(page, "06-review-phone-320");
    expect(writes.profiles).toHaveLength(2);
    expect(writes.learning).toHaveLength(0);
    expect(await sessions()).toHaveLength(0);
  } finally { await context.close(); }
});

test("a failed first probe recovers MATH210 and keeps its accepted session through later reloads", async ({ browser }) => {
  test.skip(killSwitchLane, "accepted-opener recovery requires the default learning-loop lane");
  test.setTimeout(120_000);
  const { context, page } = await signIn(browser);
  const writes = observeWrites(page);
  try {
    await page.goto(`${FRONTEND_URL}/onboarding`);
    await step(page, 1);
    await names(page);
    await page.getByTestId("onboarding-continue").click();
    await step(page, 2);
    await academics(page);
    await page.getByTestId("onboarding-continue").click();
    await step(page, 3);
    const computerScience = await selectRealCourse(page);
    const mathematics = await selectRealCourse(page, "MATH210");
    await page.getByTestId("onboarding-continue").click();
    await step(page, 4);
    const enrolled = await queryRaw(
      `SELECT o.course_id FROM enrollments e JOIN course_offerings o ON o.id = e.offering_id
        WHERE e.user_id = $1 ORDER BY o.course_id`, [USER_NEW],
    );
    expect(enrolled.map(value => value.course_id).sort()).toEqual([computerScience.id, mathematics.id].sort());
    await page.getByTestId("onboarding-skip-materials").click();
    await step(page, 5);
    // Explicitly choose the second course, rather than the initial selection.
    await expect(page.getByTestId("onboarding-goal-course")).toHaveValue(computerScience.id);
    await page.getByTestId("onboarding-goal-course").selectOption(mathematics.id);
    await expect(page.getByTestId("onboarding-goal-course-scope")).toBeChecked();
    await page.getByTestId("onboarding-continue").click();
    await step(page, 6);
    await expect(page.getByTestId("onboarding-gate")).toContainText("MATH210");
    expect(writes.starts).toHaveLength(0);
    expect(await sessions()).toHaveLength(0);

    // The real start accepts one session ID; only the following first probe
    // fails at the transport. It has not yet materialised a sessions row.
    await page.route("**/api/learn/loop/probe/next", route => route.fulfill({
      status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Probe temporarily unavailable" }),
    }));
    const accepted = page.waitForResponse(response => new URL(response.url()).pathname === "/api/learn/loop/start-session");
    const failedProbe = page.waitForResponse(response => new URL(response.url()).pathname === "/api/learn/loop/probe/next" && response.status() === 503);
    await page.getByTestId("onboarding-continue").click();
    const acceptedResponse = await accepted;
    expect(acceptedResponse.ok()).toBe(true);
    const { session_id: acceptedId } = await acceptedResponse.json() as { session_id: string };
    expect(acceptedId).toBeTruthy();
    await failedProbe;
    const canonical = `${FRONTEND_URL}/learn?course=${encodeURIComponent(mathematics.id)}`;
    await expect(page).toHaveURL(canonical);
    const phase = page.getByTestId("app-shell").getByTestId("loop-phase");
    await expect(phase).toHaveAttribute("data-session-id", acceptedId);
    expect(writes.starts).toHaveLength(1);
    expect(writes.starts[0].postDataJSON()).toMatchObject({ user_id: USER_NEW, course_id: mathematics.id, goal: null });
    const savedIntent = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key) || "null"),
      `sapling:onboarding-learning:v1:${encodeURIComponent(USER_NEW)}`);
    expect(savedIntent).toMatchObject({ userId: USER_NEW, courseId: mathematics.id, startedSessionId: acceptedId, goal: null });

    // A deliberate bare /learn visit must also discover the owned pending
    // course and recover its accepted opener, then retain that route context.
    await page.unroute("**/api/learn/loop/probe/next");
    await page.goto(`${FRONTEND_URL}/learn`);
    await expect(page).toHaveURL(canonical);
    await expect(phase).toHaveAttribute("data-session-id", acceptedId, { timeout: 30_000 });
    await expect.poll(async () => (await sessions()).length).toBe(1);
    expect((await sessions()).map(value => ({ id: value.id, course_id: value.course_id }))).toEqual([
      { id: acceptedId, course_id: mathematics.id },
    ]);
    expect(writes.starts).toHaveLength(1);
    expect(writes.starts.some(request => request.postDataJSON().course_id === computerScience.id)).toBe(false);
    const intentKey = `sapling:onboarding-learning:v1:${encodeURIComponent(USER_NEW)}`;
    await expect.poll(() => page.evaluate(key => sessionStorage.getItem(key), intentKey)).toBeNull();
    for (let refresh = 0; refresh < 2; refresh++) {
      await page.reload();
      await expect(page).toHaveURL(canonical);
      await expect(phase).toHaveAttribute("data-session-id", acceptedId, { timeout: 30_000 });
      await expect(page.getByTestId("loop-course-select")).toContainText("MATH210");
      expect(await page.evaluate(key => sessionStorage.getItem(key), intentKey)).toBeNull();
      expect(writes.starts).toHaveLength(1);
      expect((await sessions()).map(value => ({ id: value.id, course_id: value.course_id }))).toEqual([
        { id: acceptedId, course_id: mathematics.id },
      ]);
    }
    await evidence(page, "08-recovered-math-check-in-desktop");
  } finally { await context.close(); }
});
