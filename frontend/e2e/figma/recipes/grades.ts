import { expect, type Page, type Route } from "@playwright/test";

import { COURSE_CS101, hold, mockError, mockJson, storage, text, visible } from "../helpers";
import type { Recipe, RecipeBook } from "../types";

/**
 * 03 — gradebook / course / Gradescope / calendar / course planner /
 * achievements / social / profile / ManageCoursesModal
 * (docs/figma/inventory/03-gradebook-calendar-social.md).
 *
 * Everything that would write is either mocked (with its method) or armed
 * without confirming — the showcase DB is shared by the whole run.
 */

// ── ids + small helpers ─────────────────────────────────────────────────────

const ME = "rich-user-active";
const SECOND = "rich-user-second";
const ROOM_STUDY = "rich-room-study-group";
const ROOM_LOUNGE = "rich-room-general";

const CS101_S26 = `/gradebook/${COURSE_CS101}?semester=Spring%202026`;
const BIO110_F25 = "/gradebook/rich-course-bio110?semester=Fall%202025";

/** GET /api/gradebook/courses/{id}?… — never the categories/scale/curve subpaths. */
const COURSE_DETAIL = /\/api\/gradebook\/courses\/[^/?]+\?/;
const MY_COURSES = new RegExp(`/api/graph/${ME}/courses$`);
const MY_ROOMS = new RegExp(`/api/social/rooms/${ME}$`);
const MY_FRIENDS = new RegExp(`/api/social/friends/${ME}$`);
const FRIEND_REQUESTS = "/api/social/friends/requests";
const MY_ACHIEVEMENTS = new RegExp(`/api/profile/${ME}/achievements$`);
const SECOND_PROFILE = new RegExp(`/api/profile/${SECOND}$`);
const ROOM_OVERVIEW = /\/api\/social\/rooms\/[^/]+\/overview$/;
const STUDY_MESSAGES = `/api/social/rooms/${ROOM_STUDY}/messages`;
/** Messages GET of every room EXCEPT the study group. */
const OTHER_ROOM_MESSAGES = new RegExp(`^/api/social/rooms/(?!${ROOM_STUDY}/)[^/]+/messages`);

function urlMatches(pattern: RegExp) {
  return (url: URL) => pattern.test(url.pathname + url.search);
}

/** Fetch the real response and rewrite its JSON body. */
async function patchJson(
  page: Page,
  pattern: RegExp,
  fn: (body: Record<string, unknown>) => unknown,
  method = "GET",
): Promise<void> {
  await page.route(urlMatches(pattern), async (route: Route) => {
    if (route.request().method() !== method) return route.fallback();
    const res = await route.fetch();
    const body = (await res.json()) as Record<string, unknown>;
    await route.fulfill({ response: res, json: fn(body) });
  });
}

/**
 * Drop setTimeout callbacks with exactly these delays, so an armed "Click
 * again" (useConfirm, 3000ms), a toast (5000/6000ms), a "Copied!" (2000ms)
 * or the category highlight (1600ms) is still on screen when the harness
 * captures. Must run before goto.
 */
async function pinTimers(page: Page, delays: number[]): Promise<void> {
  await page.addInitScript((ds: number[]) => {
    const w = window as unknown as { setTimeout: (...a: unknown[]) => number };
    const orig = w.setTimeout.bind(window);
    w.setTimeout = (fn: unknown, ms?: unknown, ...rest: unknown[]) =>
      ds.includes(Number(ms)) ? 0 : orig(fn, ms, ...rest);
  }, delays);
}

const TOASTS = [5000, 6000];
const ARMED = [3000];

function dialog(page: Page) {
  return page.getByRole("dialog").last();
}

// ── gradebook fixtures ──────────────────────────────────────────────────────

const summaryCard = (
  course_id: string,
  course_code: string,
  course_name: string,
  percent: number | null,
  letter: string | null,
  graded_count: number,
  total_count: number,
) => ({ course_id, course_code, course_name, semester: "Spring 2026", percent, letter, graded_count, total_count });

const GRADE_COLOR_CARDS = {
  semester: "Spring 2026",
  gpa: 2.85,
  courses: [
    summaryCard(COURSE_CS101, "CS101", "Introduction to Computer Science", 95.2, "A", 9, 12),
    summaryCard("rich-course-math210", "MATH210", "Calculus II", 85.4, "B", 7, 10),
    summaryCard("rich-course-bio110", "BIO110", "Principles of Biology", 76.1, "C", 6, 9),
    summaryCard("rich-course-eng150", "ENG150", "College Writing", 64.8, "D", 4, 8),
    summaryCard("rich-course-hist200", "HIST200", "Modern World History", 52.3, "F", 3, 7),
    summaryCard("rich-course-chem121", "CHEM121", "General Chemistry", null, null, 0, 6),
  ],
};

const cat = (id: string, name: string, weight: number, sort_order: number, drop_lowest = 0) => ({
  id,
  name,
  weight,
  sort_order,
  drop_lowest,
});

const asg = (
  id: string,
  title: string,
  category_id: string | null,
  points_earned: number | null,
  points_possible: number | null,
  due_date: string | null,
  extra: Record<string, unknown> = {},
) => ({
  id,
  title,
  course_id: COURSE_CS101,
  category_id,
  points_possible,
  points_earned,
  due_date,
  assignment_type: "homework",
  notes: null,
  source: "manual",
  curve_class_mean: null,
  curve_class_sd: null,
  curve_avg_target: null,
  curve_sd_delta: null,
  ...extra,
});

const CATS = [
  cat("fig-cat-hw", "Homework", 30, 0),
  cat("fig-cat-proj", "Projects", 30, 1),
  cat("fig-cat-exam", "Exams", 30, 2),
  cat("fig-cat-part", "Participation", 10, 3),
];

const ASGS = [
  asg("fig-a-hw1", "Problem Set 1", "fig-cat-hw", 9, 10, "2026-01-30"),
  asg("fig-a-hw2", "Problem Set 2", "fig-cat-hw", 7, 10, "2026-02-13"),
  asg("fig-a-hw3", "Problem Set 3", "fig-cat-hw", null, 10, "2026-03-20"),
  asg("fig-a-p1", "Project 1: Text Adventure", "fig-cat-proj", 46, 50, "2026-02-20"),
  asg("fig-a-p2", "Project 2: Recursion Lab", "fig-cat-proj", null, 50, "2026-04-03"),
  asg("fig-a-mid", "Midterm Exam", "fig-cat-exam", null, 100, "2026-03-18"),
];

function course(over: Record<string, unknown> = {}) {
  return {
    course_id: COURSE_CS101,
    course_code: "CS101",
    course_name: "Introduction to Computer Science",
    semester: "Spring 2026",
    percent: 87.6,
    letter: "B+",
    letter_scale: null,
    curve_mode: "raw",
    curve_avg_target: null,
    curve_sd_delta: null,
    categories: CATS,
    assignments: ASGS,
    dropped_assignment_ids: [],
    ...over,
  };
}

/** A curved course: one graded exam with class stats + one ungraded with stats. */
const CURVED = course({
  curve_mode: "curved",
  curve_avg_target: 0.83,
  curve_sd_delta: 0.1,
  assignments: [
    ...ASGS.filter((a) => a.id !== "fig-a-mid"),
    asg("fig-a-mid", "Midterm Exam", "fig-cat-exam", 72, 100, "2026-03-04", {
      curve_class_mean: 0.68,
      curve_class_sd: 0.12,
    }),
    asg("fig-a-final", "Final Exam", "fig-cat-exam", null, 100, "2026-05-08", {
      curve_class_mean: 0.7,
      curve_class_sd: 0.1,
    }),
  ],
});

async function openCourse(page: Page, body?: unknown): Promise<void> {
  if (body !== undefined) await mockJson(page, COURSE_DETAIL, body, { method: "GET" });
  await page.goto(CS101_S26);
  await expect(page.getByRole("heading", { name: "Introduction to Computer Science" })).toBeVisible({
    timeout: 30_000,
  });
}

/** Hover a composition-bar sub-segment without moving the real pointer. */
async function hoverSegment(page: Page, categoryName: string, nth: number): Promise<void> {
  const seg = page.locator(`div[title="Jump to ${categoryName} assignments"] > div`).nth(nth);
  await expect(seg).toBeVisible({ timeout: 30_000 });
  const box = (await seg.boundingBox())!;
  const init = { bubbles: true, clientX: box.x + box.width / 2, clientY: box.y + box.height / 2 };
  await seg.dispatchEvent("mouseover", init);
  await seg.dispatchEvent("mousemove", init);
  await expect(page.getByRole("tooltip")).toBeVisible();
}

// ── Gradescope fixtures ─────────────────────────────────────────────────────

const GS_CONNECTED = { has_credentials: true, auth_mode: "password", last_synced_at: "2026-03-11T11:55:00Z" };
const GS_LINKS = {
  links: [
    {
      id: "fig-gs-link",
      sapling_course_id: COURSE_CS101,
      gradescope_course_id: "812345",
      last_synced_at: "2026-03-11T11:55:00Z",
    },
  ],
};
const GS_COURSES = {
  courses: [
    { id: "812345", name: "CS 101", full_name: "CS 101: Introduction to Computer Science", semester: "Spring", year: "2026", num_assignments: "14" },
    { id: "812377", name: "MA 210", full_name: "Calculus II", semester: "Spring", year: "2026", num_assignments: "9" },
    { id: "799120", name: "BI 110", full_name: "Principles of Biology", semester: "Fall", year: "2025", num_assignments: "11" },
  ],
};

async function gsLinked(page: Page): Promise<void> {
  await mockJson(page, "/api/gradescope/status", GS_CONNECTED);
  await mockJson(page, "/api/gradescope/links", GS_LINKS);
}

async function gsUnlinked(page: Page, courses: unknown = GS_COURSES): Promise<void> {
  await mockJson(page, "/api/gradescope/status", GS_CONNECTED);
  await mockJson(page, "/api/gradescope/links", { links: [] });
  await mockJson(page, "/api/gradescope/courses", courses);
}

async function openGsModal(page: Page): Promise<void> {
  await openCourse(page);
  await page.getByRole("button", { name: "Set Up Gradescope Sync" }).click();
}

async function openGsReady(page: Page): Promise<void> {
  await gsLinked(page);
  await openCourse(page);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Pull grades from Gradescope" })).toBeVisible();
}

// ── syllabus flow ───────────────────────────────────────────────────────────

const SYLLABUS_FILE = { name: "cs101-syllabus.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%figma\n") };

const syllabusExtract = (weights: number[]) => ({
  id: "fig-doc-syllabus",
  doc_id: "fig-doc-syllabus",
  category: "syllabus",
  summary: null,
  categories: [
    { name: "Homework", weight: weights[0] },
    { name: "Projects", weight: weights[1] },
    { name: "Exams", weight: weights[2] },
  ],
  assignments: [
    { title: "Problem Set 5", due_date: "2026-03-20", assignment_type: "homework", notes: null },
    { title: "Problem Set 6", due_date: "2026-03-27", assignment_type: "homework", notes: null },
    { title: "Project 2: Recursion Lab", due_date: "2026-04-03", assignment_type: "project", notes: null },
    { title: "Final Exam", due_date: "2026-05-08", assignment_type: "exam", notes: null },
  ],
});

async function syllabusPick(page: Page): Promise<void> {
  await page.goto("/gradebook");
  await visible(page, "gradebook-transcript-open");
  await page.getByRole("button", { name: "Upload syllabus" }).first().click();
  const select = dialog(page).getByLabel("Course");
  await expect(select.locator(`option[value="${COURSE_CS101}"]`)).toHaveCount(1, { timeout: 30_000 });
  await select.selectOption(COURSE_CS101);
}

async function syllabusReview(page: Page, weights = [30, 30, 40]): Promise<void> {
  await mockJson(page, "/api/documents/upload/sync", syllabusExtract(weights), { method: "POST" });
  await syllabusPick(page);
  await dialog(page).locator('input[type="file"]').setInputFiles(SYLLABUS_FILE);
  await expect(dialog(page).getByText("Assignments (4)")).toBeVisible({ timeout: 30_000 });
}

// ── calendar fixtures ───────────────────────────────────────────────────────

const calItem = (id: string, title: string, due_date: string | null, assignment_type: string, code: string, name: string, course_id: string) => ({
  id,
  user_id: ME,
  title,
  due_date,
  assignment_type,
  course_id,
  course_code: code,
  course_name: name,
});

const CAL_ITEMS = [
  calItem("fig-cal-1", "Problem Set 4", "2026-03-06", "homework", "CS101", "Introduction to Computer Science", COURSE_CS101),
  calItem("fig-cal-2", "Lab 5: Enzymes", "2026-03-11", "lab", "BIO110", "Principles of Biology", "rich-course-bio110"),
  calItem("fig-cal-3", "Quiz 3", "2026-03-12", "quiz", "MATH210", "Calculus II", "rich-course-math210"),
  calItem("fig-cal-4", "Midterm Exam", "2026-03-18", "exam", "CS101", "Introduction to Computer Science", COURSE_CS101),
  calItem("fig-cal-5", "Essay Draft", "2026-03-24", "essay", "ENG150", "College Writing", "rich-course-eng150"),
  calItem("fig-cal-6", "Participation", null, "other", "CS101", "Introduction to Computer Science", COURSE_CS101),
];

const GOOGLE_EVENTS = {
  count: 3,
  events: [
    { google_event_id: "fig-g-1", title: "CS101 Office Hours", start_date: "2026-03-12", end_date: "2026-03-12", start_datetime: "2026-03-12T15:00:00-04:00", all_day: false, location: "CDS 164", html_link: "https://calendar.google.com" },
    { google_event_id: "fig-g-2", title: "Study group — Recursion", description: "Bring the call-stack worksheet.", start_date: "2026-03-14", end_date: "2026-03-14", start_datetime: "2026-03-14T18:30:00-04:00", all_day: false },
    { google_event_id: "fig-g-3", title: "Spring Break", start_date: "2026-03-21", end_date: "2026-03-29", all_day: true },
  ],
};

async function calendarReady(page: Page, url = "/calendar"): Promise<void> {
  await page.goto(url);
  await expect(page.getByText("Mon", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
}

async function googleConnected(page: Page): Promise<void> {
  await mockJson(page, "/api/calendar/status/", { connected: true, expires_at: "2026-04-11T12:00:00Z" });
}

// ── achievements fixtures ───────────────────────────────────────────────────

const ach = (id: string, name: string, category: string, rarity: string, description: string, extra: Record<string, unknown> = {}) => ({
  id,
  name,
  slug: id,
  description,
  icon: "🌱",
  category,
  rarity,
  is_secret: false,
  progress: null,
  xp_reward: 50,
  icon_url: null,
  sort_order: 1,
  status: "live",
  ...extra,
});

function achievementsBody(featured: boolean) {
  return {
    earned: [
      { achievement: ach("fig-ach-first", "First Sprout", "activity", "common", "Finish your first tutoring session.", { icon: "🌱" }), earned_at: "2026-02-02T15:00:00Z", is_featured: featured },
      { achievement: ach("fig-ach-streak", "Week-Long Streak", "activity", "uncommon", "Study seven days in a row.", { icon: "🔥", xp_reward: 100 }), earned_at: "2026-02-19T15:00:00Z", is_featured: featured },
      { achievement: ach("fig-ach-buddy", "Study Buddy", "social", "rare", "Join a study room with a classmate.", { icon: "🤝" }), earned_at: "2026-03-01T15:00:00Z", is_featured: featured },
    ],
    available: [
      ach("fig-ach-quiz", "Quiz Ace", "milestone", "rare", "Score 100% on ten quizzes.", { icon: "🎯", progress: { current: 6, target: 10 }, xp_reward: 150 }),
      ach("fig-ach-mentor", "Mentor", "social", "uncommon", "Answer five classmates' questions in a room.", { icon: "🗣️", progress: { current: 3, target: 5 } }),
      ach("fig-ach-owl", "Night Owl", "special", "epic", "Finish a session after midnight.", { icon: "🦉", xp_reward: 200 }),
      ach("fig-ach-secret", "Hidden Grove", "special", "legendary", "Found the hidden grove.", { is_secret: true, xp_reward: 500 }),
    ],
  };
}

async function achievementsPage(page: Page, body: unknown = achievementsBody(false)): Promise<void> {
  await mockJson(page, MY_ACHIEVEMENTS, body, { method: "GET" });
  await page.goto("/achievements");
  await expect(page.getByText("Showcase · featured on your profile")).toBeVisible({ timeout: 30_000 });
}

const lbRow = (rank: number, user_id: string, name: string, week_xp: number, is_you = false) => ({
  rank,
  user_id,
  name,
  level: Math.max(1, 9 - rank),
  stage: rank <= 2 ? "Sapling" : "Sprout",
  total_xp: week_xp * 6,
  week_xp,
  streak: Math.max(0, 8 - rank),
  is_you,
});

const LB_ROWS = [
  lbRow(1, "fig-u-priya", "Priya Raman", 1240),
  lbRow(2, ME, "Maya Ellis", 980, true),
  lbRow(3, SECOND, "Jordan Lee", 860),
  lbRow(4, "fig-u-sam", "Sam Okafor", 610),
  lbRow(5, "fig-u-lena", "Lena Fischer", 430),
  lbRow(6, "fig-u-theo", "Theo Park", 210),
];

/** `body` is the JSON to serve, or "hold" / "error". */
async function leaderboard(page: Page, body: unknown): Promise<void> {
  if (body === "hold") await hold(page, "/api/gamification/leaderboard");
  else if (body === "error") await mockError(page, "/api/gamification/leaderboard");
  else await mockJson(page, "/api/gamification/leaderboard", body);
  await page.goto("/achievements");
  await page.getByTestId("achievements-tab-leaderboard").click({ timeout: 30_000 });
}

const ACTIVITY = {
  daily_goal_xp: 60,
  week: [
    { day: "Mon", date: "2026-03-09", xp: 80 },
    { day: "Tue", date: "2026-03-10", xp: 45 },
    { day: "Wed", date: "2026-03-11", xp: 70 },
    { day: "Thu", date: "2026-03-12", xp: 0 },
    { day: "Fri", date: "2026-03-13", xp: 0 },
    { day: "Sat", date: "2026-03-14", xp: 0 },
    { day: "Sun", date: "2026-03-15", xp: 0 },
  ],
  trend: [
    { label: "Jan 19", xp: 120 },
    { label: "Jan 26", xp: 210 },
    { label: "Feb 2", xp: 180 },
    { label: "Feb 9", xp: 260 },
    { label: "Feb 16", xp: 310 },
    { label: "Feb 23", xp: 240 },
    { label: "Mar 2", xp: 330 },
    { label: "Mar 9", xp: 195 },
  ],
  tiles: { week_total: 195, daily_avg: 65, best_day: 80, best_day_label: "Mon", streak: 6 },
};

/** `body` is the JSON to serve, or "hold" / "error". */
async function activity(page: Page, body: unknown): Promise<void> {
  if (body === "hold") await hold(page, "/api/gamification/activity");
  else if (body === "error") await mockError(page, "/api/gamification/activity");
  else await mockJson(page, "/api/gamification/activity", body);
  await page.goto("/achievements");
  await page.getByTestId("achievements-tab-activity").click({ timeout: 30_000 });
}

// ── social fixtures ─────────────────────────────────────────────────────────

const msg = (id: string, user_id: string, user_name: string, text: string | null, created_at: string, extra: Record<string, unknown> = {}) => ({
  id,
  user_id,
  user_name,
  text,
  image_url: null,
  created_at,
  reply_to_id: null,
  is_deleted: false,
  edited_at: null,
  reply_to: null,
  reactions: [],
  ...extra,
});

const IMAGE =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="140"><rect width="240" height="140" rx="10" fill="#eef3e6"/>' +
      '<g fill="#5b7f3a" font-family="monospace" font-size="13"><text x="20" y="36">fact(3)</text><text x="40" y="66">fact(2)</text>' +
      '<text x="60" y="96">fact(1)</text><text x="80" y="126">fact(0) = 1</text></g></svg>',
  );

const STUDY_MSGS = [
  msg("fig-msg-1", SECOND, "Jordan Lee", "Anyone want to go over recursion before Friday's quiz?", "2026-03-11T14:02:00Z"),
  msg("fig-msg-2", ME, "Maya Ellis", "Yes! I keep tripping on the base case.", "2026-03-11T14:04:00Z", {
    reactions: [{ emoji: "👍", user_ids: [SECOND] }],
  }),
  msg("fig-msg-3", SECOND, "Jordan Lee", null, "2026-03-11T14:05:00Z", { is_deleted: true }),
  msg("fig-msg-4", SECOND, "Jordan Lee", "Here's the call-stack sketch from lecture", "2026-03-11T14:06:00Z", {
    image_url: IMAGE,
    image_width: 240,
    image_height: 140,
  }),
  msg("fig-msg-5", ME, "Maya Ellis", "Fixed my factorial — it was the n == 0 check", "2026-03-11T14:09:00Z", {
    edited_at: "2026-03-11T14:10:00Z",
    reply_to_id: "fig-msg-1",
    reply_to: { id: "fig-msg-1", user_name: "Jordan Lee", text: "Anyone want to go over recursion before Friday's quiz?" },
    reactions: [
      { emoji: "🎉", user_ids: [SECOND, ME] },
      { emoji: "🔥", user_ids: [SECOND] },
    ],
  }),
  msg("fig-msg-6", SECOND, "Jordan Lee", "@MayaEllis nice — want to pair on the tree problems tonight?", "2026-03-11T14:12:00Z"),
];

async function studyRoom(page: Page, messages?: unknown): Promise<void> {
  // Social auto-selects rooms[0] (not the study group) before our click, and
  // RoomChat is not keyed by room: that room's slower real messages fetch can
  // land AFTER the study group's (instant, mocked) one and overwrite it. Hold
  // every other room's messages so only the study group's ever render.
  await hold(page, OTHER_ROOM_MESSAGES, "GET");
  if (messages !== undefined) await mockJson(page, STUDY_MESSAGES, messages, { method: "GET" });
  await page.goto("/social");
  await page.getByTestId(`social-room-item-${ROOM_STUDY}`).click({ timeout: 30_000 });
  await expect(page.getByTestId("social-room-name")).toContainText("CS101", { timeout: 15_000 });
}

async function studyChat(page: Page): Promise<void> {
  await studyRoom(page, { messages: STUDY_MSGS, has_more: false });
  await visible(page, "social-chat-message-fig-msg-6");
}

async function openBubbleMenu(page: Page, id: string, textInBubble: string): Promise<void> {
  await page.getByTestId(`social-chat-message-${id}`).getByText(textInBubble).click();
  await visible(page, "social-chat-message-react");
}

async function roomTab(page: Page, label: string): Promise<void> {
  await page.getByRole("button", { name: label, exact: true }).click();
}

const node = (concept_name: string, mastery_score: number) => ({ id: `fig-n-${concept_name}`, concept_name, mastery_score, is_subject_root: false });

const OVERVIEW_COMPARE = {
  room: { id: ROOM_STUDY, name: "CS101 Study Group", invite_code: "CS101-FALL", created_by: ME, owner_id: ME },
  ai_summary:
    "The group is strongest on loops and conditionals and is working through recursion together. Jordan is ahead on trees; Maya leads on big-O.",
  members: [
    { user_id: ME, name: "Maya Ellis", graph: { edges: [], nodes: [node("Recursion", 0.35), node("Binary Trees", 0.2), node("Big-O", 0.8), node("Loops", 0.9)] } },
    { user_id: SECOND, name: "Jordan Lee", graph: { edges: [], nodes: [node("Recursion", 0.75), node("Binary Trees", 0.7), node("Big-O", 0.5), node("Loops", 0.85)] } },
  ],
};

const friend = (user_id: string, name: string, level: number, total_xp: number) => ({ user_id, name, level, total_xp });

async function socialFriends(page: Page, friends: unknown[], incoming: unknown[] = [], outgoing: unknown[] = []): Promise<void> {
  await mockJson(page, MY_FRIENDS, { friends });
  await mockJson(page, FRIEND_REQUESTS, { incoming, outgoing });
  await page.goto("/social");
  await expect(page.getByText("Study Rooms")).toBeVisible({ timeout: 30_000 });
}

const PUBLIC_ROOMS = {
  rooms: [
    { id: "fig-room-pub-1", name: "Organic Chem Night Owls", topic: "Exam 2 review", course: "CHEM121", owner_id: "fig-u-priya", created_by: "fig-u-priya", created_at: "2026-03-01T12:00:00Z", updated_at: null, is_public: true, member_count: 6 },
    { id: "fig-room-pub-2", name: "Calc II Problem Grind", topic: "Series & sequences", course: "MATH210", owner_id: "fig-u-sam", created_by: "fig-u-sam", created_at: "2026-03-04T12:00:00Z", updated_at: null, is_public: true, member_count: 4 },
  ],
};

// ── profile fixtures ────────────────────────────────────────────────────────

function profileBody(over: Record<string, unknown> = {}) {
  return {
    id: SECOND,
    name: "Jordan Lee",
    username: "jordanlee",
    bio: "CS + math. Usually found in the library's third floor with too much coffee.",
    location: "Boston, MA",
    website: null,
    avatar_url: null,
    created_at: "2025-09-01T00:00:00Z",
    year: "Sophomore",
    majors: ["Computer Science"],
    minors: ["Mathematics"],
    school: "Rich Local University",
    roles: [],
    featured_achievements: [],
    equipped_cosmetics: {},
    stats: { streak_count: 5, session_count: 22, documents_count: 7, achievements_count: 4 },
    ...over,
  };
}

async function profileOf(page: Page, friends: unknown[] = [], outgoing: unknown[] = []): Promise<void> {
  await mockJson(page, MY_FRIENDS, { friends });
  await mockJson(page, FRIEND_REQUESTS, { incoming: [], outgoing });
  await page.goto(`/profile/${SECOND}`);
}

// ── ManageCoursesModal ──────────────────────────────────────────────────────

const SEARCH_RESULTS = {
  courses: [
    { id: COURSE_CS101, course_code: "CS101", course_name: "Introduction to Computer Science" },
    { id: "fig-cat-math242", course_code: "MATH242", course_name: "Linear Algebra" },
    { id: "fig-cat-phys211", course_code: "PHYS211", course_name: "Mechanics" },
  ],
};

async function openManageCourses(page: Page): Promise<void> {
  await page.goto("/dashboard");
  await page.getByTestId("dashboard-courses-key-toggle").click({ timeout: 30_000 });
  await page.getByTestId("dashboard-courses-manage").click();
  await expect(page.getByText("Courses & Semesters").last()).toBeVisible();
}

// ═════════════════════════════════════════════════════════════════════════════

const gradebook: RecipeBook = {
  "gradebook/loading": {
    run: async (page) => {
      await hold(page, "/api/gradebook/summary");
      await page.goto("/gradebook");
      await visible(page, "gradebook-transcript-open");
      await expect(page.locator(".skeleton").first()).toBeVisible();
    },
  },

  "gradebook/populated": {
    run: async (page) => {
      await page.goto("/gradebook");
      await expect(page.getByRole("grid", { name: "Courses" })).toBeVisible({ timeout: 30_000 });
      await visible(page, "gradebook-term-gpa");
    },
  },

  "gradebook/populated-no-gpa": {
    run: async (page) => {
      await patchJson(page, /\/api\/gradebook\/summary/, (b) => ({ ...b, gpa: null }));
      await page.goto("/gradebook");
      await expect(page.getByRole("grid", { name: "Courses" })).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("gradebook-term-gpa")).toHaveCount(0);
    },
  },

  "gradebook/card-awaiting-grade": {
    run: async (page) => {
      await mockJson(page, "/api/gradebook/summary", GRADE_COLOR_CARDS);
      await page.goto("/gradebook");
      await text(page, "Awaiting First Assignment");
    },
  },

  "gradebook/card-grade-colors": {
    run: async (page) => {
      await mockJson(page, "/api/gradebook/summary", GRADE_COLOR_CARDS);
      await page.goto("/gradebook");
      const grid = page.getByRole("grid", { name: "Courses" });
      await expect(grid.getByRole("link")).toHaveCount(6, { timeout: 30_000 });
    },
  },

  "gradebook/chip-past-term": {
    run: async (page) => {
      await page.goto("/gradebook?semester=Fall%202025");
      await expect(page.getByRole("button", { name: "Fall 2025", exact: true })).toHaveAttribute(
        "aria-pressed",
        "true",
        { timeout: 30_000 },
      );
      await expect(page.getByRole("grid", { name: "Courses" })).toBeVisible();
    },
  },

  "gradebook/empty-term": {
    run: async (page) => {
      await mockJson(page, "/api/gradebook/summary", { courses: [], gpa: null, semester: "Spring 2026" });
      await page.goto("/gradebook");
      await visible(page, "gradebook-upload-syllabus");
      await text(page, "A blank semester, ready to plant.");
    },
  },

  "gradebook/empty-new-student": {
    run: async (page) => {
      await mockJson(page, MY_COURSES, { courses: [] }, { method: "GET" });
      await page.goto("/gradebook");
      await text(page, "A blank semester, ready to plant.");
      await expect(page.getByRole("button", { name: "Spring 2026", exact: true })).toHaveCount(0);
    },
  },

  "gradebook/syllabus-pick-course": {
    run: async (page) => {
      await syllabusPick(page);
      await expect(dialog(page).getByLabel("Course")).toHaveValue(COURSE_CS101);
    },
  },

  "gradebook/syllabus-extracting": {
    run: async (page) => {
      await hold(page, "/api/documents/upload/sync", "POST");
      await syllabusPick(page);
      await dialog(page).locator('input[type="file"]').setInputFiles(SYLLABUS_FILE);
      await expect(dialog(page).getByText("Extracting syllabus…")).toBeVisible();
    },
  },

  "gradebook/syllabus-review": {
    run: async (page) => {
      await syllabusReview(page);
      await expect(dialog(page).getByText(/Total: 100\.0% ✓/)).toBeVisible();
    },
  },

  "gradebook/syllabus-review-invalid": {
    run: async (page) => {
      await syllabusReview(page, [30, 30, 30]);
      await expect(dialog(page).getByText(/need 100%/)).toBeVisible();
      await expect(dialog(page).getByRole("button", { name: "Save to gradebook" })).toBeDisabled();
    },
  },

  "gradebook/syllabus-saving": {
    run: async (page) => {
      await hold(page, "/api/gradebook/syllabus/apply", "POST");
      await syllabusReview(page);
      await dialog(page).getByRole("button", { name: "Save to gradebook" }).click();
      await expect(dialog(page).getByText("Saving…")).toBeVisible();
    },
  },

  "gradebook/syllabus-saved": {
    run: async (page) => {
      await pinTimers(page, TOASTS);
      await mockJson(page, "/api/gradebook/syllabus/apply", { course: course() }, { method: "POST" });
      await syllabusReview(page);
      await dialog(page).getByRole("button", { name: "Save to gradebook" }).click();
      await text(page, "Syllabus applied");
      await expect(page).toHaveURL(new RegExp(`/gradebook/${COURSE_CS101}`));
    },
  },

  "gradebook/syllabus-save-error": {
    run: async (page) => {
      await pinTimers(page, TOASTS);
      await mockError(page, "/api/gradebook/syllabus/apply", 500, "Couldn't apply the syllabus", "POST");
      await syllabusReview(page);
      await dialog(page).getByRole("button", { name: "Save to gradebook" }).click();
      await text(page, /Save failed/);
    },
  },

  "gradebook/transcript-loading": {
    run: async (page) => {
      await hold(page, "/api/gradebook/gpa");
      await page.goto("/gradebook");
      await page.getByTestId("gradebook-transcript-open").click({ timeout: 30_000 });
      await expect(dialog(page).locator(".skeleton").first()).toBeVisible();
    },
  },

  "gradebook/transcript-populated": {
    run: async (page) => {
      await page.goto("/gradebook");
      await page.getByTestId("gradebook-transcript-open").click({ timeout: 30_000 });
      await expect(page.getByTestId("gradebook-transcript-gpa")).toHaveText(/\d\.\d\d/, { timeout: 30_000 });
    },
  },

  "gradebook/transcript-empty": {
    run: async (page) => {
      await mockJson(page, "/api/gradebook/gpa", { gpa: null, courses: [], semester: null, scope: "cumulative" });
      await page.goto("/gradebook");
      await page.getByTestId("gradebook-transcript-open").click({ timeout: 30_000 });
      await expect(dialog(page).getByText(/Nothing on the transcript yet/)).toBeVisible();
    },
  },

  "gradebook/transcript-error": {
    run: async (page) => {
      await mockError(page, "/api/gradebook/gpa");
      await page.goto("/gradebook");
      await page.getByTestId("gradebook-transcript-open").click({ timeout: 30_000 });
      await visible(page, "gradebook-transcript-retry");
    },
  },
};

const coursePage: RecipeBook = {
  "course/loading": {
    run: async (page) => {
      await hold(page, COURSE_DETAIL, "GET");
      await page.goto(CS101_S26);
      await expect(page.getByRole("link", { name: "← Gradebook" })).toBeVisible({ timeout: 30_000 });
      await expect(page.locator("main .skeleton").first()).toBeVisible();
    },
  },

  "course/error": {
    run: async (page) => {
      await mockError(page, COURSE_DETAIL, 404, "Course not in your gradebook", "GET");
      await page.goto(CS101_S26);
      await text(page, "We couldn't load this course.");
    },
  },

  "course/populated": {
    run: async (page) => {
      await openCourse(page);
      await visible(page, "gradebook-add-assignment");
      await text(page, "Composition");
    },
  },

  "course/masthead-empty": {
    run: async (page) => {
      await openCourse(
        page,
        course({
          percent: null,
          letter: null,
          assignments: ASGS.map((a) => ({ ...a, points_earned: null })),
        }),
      );
      await expect(page.locator("header").getByText("—").first()).toBeVisible();
    },
  },

  "course/composition-status-variants": {
    run: async (page) => {
      await openCourse(page, course());
      await text(page, /At the Top of the Scale|already guaranteed|out of reach by|Need \d+%\+ avg/);
    },
  },

  "course/composition-no-categories": {
    run: async (page) => {
      await openCourse(page, course({ categories: [], assignments: [], percent: null, letter: null }));
      await text(page, /No categories yet/);
      await expect(page.getByRole("button", { name: "Edit Weights" })).toBeVisible();
    },
  },

  "course/weights-not-100": {
    run: async (page) => {
      await openCourse(
        page,
        course({ categories: CATS.map((c) => (c.id === "fig-cat-part" ? { ...c, weight: 0 } : c)) }),
      );
      await text(page, /Weights sum to 90%, not 100%/);
    },
  },

  "course/drop-lowest": {
    run: async (page) => {
      await page.goto(BIO110_F25);
      await text(page, /· 1 Drops/);
      await text(page, "Dropped");
    },
  },

  "course/bar-tooltip-earned": {
    run: async (page) => {
      await openCourse(page, course());
      await hoverSegment(page, "Homework", 0);
      await expect(page.getByRole("tooltip")).toContainText("Locked-in contribution");
    },
  },

  "course/bar-tooltip-lost": {
    run: async (page) => {
      await openCourse(page, course());
      await hoverSegment(page, "Homework", 1);
      await expect(page.getByRole("tooltip")).toContainText("Cost to final");
    },
  },

  "course/bar-tooltip-remaining": {
    run: async (page) => {
      await openCourse(page, course());
      await hoverSegment(page, "Homework", 2);
      await expect(page.getByRole("tooltip")).toContainText("Still Reachable");
    },
  },

  "course/bar-tooltip-empty": {
    run: async (page) => {
      await openCourse(page, course());
      await hoverSegment(page, "Participation", 0);
      await expect(page.getByRole("tooltip")).toContainText("No graded points yet");
    },
  },

  "course/category-highlight": {
    run: async (page) => {
      await pinTimers(page, [1600]);
      await openCourse(page, course());
      // The label row under the bar: one button per category.
      await page.getByRole("button", { name: /Exams.*30%/ }).first().click();
      await expect(page.locator("#category-fig-cat-exam")).toBeVisible();
    },
  },

  "course/assignments-empty": {
    run: async (page) => {
      await openCourse(page, course({ assignments: [], percent: null, letter: null }));
      await text(page, "Nothing entered yet.");
    },
  },

  "course/assignments-uncategorized": {
    run: async (page) => {
      await openCourse(
        page,
        course({
          assignments: [
            ...ASGS,
            asg("fig-a-un1", "Extra credit reading", null, 5, 5, "2026-02-27"),
            asg("fig-a-un2", "Guest lecture reflection", null, null, 10, null),
          ],
        }),
      );
      await expect(page.locator("#category-uncategorized")).toBeVisible();
    },
  },

  "course/inline-grade-edit": {
    run: async (page) => {
      await pinTimers(page, TOASTS);
      await mockError(page, /\/api\/gradebook\/assignments\/[^/?]+/, 500, "Server unavailable", "PATCH");
      await openCourse(page, course());
      const input = page.getByRole("spinbutton", { name: "Points earned for Problem Set 3" });
      await input.fill("8");
      await input.press("Enter");
      await text(page, /Couldn't save/);
    },
  },

  "course/gradescope-setup-btn": {
    run: async (page) => {
      await mockJson(page, "/api/gradescope/status", { has_credentials: false, auth_mode: null, last_synced_at: null });
      await openCourse(page);
      await expect(page.getByRole("button", { name: "Set Up Gradescope Sync" })).toBeVisible();
    },
  },

  "course/gradescope-ready-btn": {
    run: async (page) => {
      await gsLinked(page);
      await openCourse(page);
      await expect(page.getByRole("button", { name: "Sync from Gradescope" })).toBeVisible();
      await text(page, /Synced .*ago|Synced just now/);
    },
  },

  "course/gradescope-syncing-btn": {
    run: async (page) => {
      await gsLinked(page);
      await hold(page, "/api/gradescope/sync/", "POST");
      await openCourse(page);
      await page.getByRole("button", { name: "Sync from Gradescope" }).click();
      await expect(page.getByRole("button", { name: "Syncing…" })).toBeVisible();
    },
  },

  "course/curve-toggle": {
    run: async (page) => {
      await openCourse(page, CURVED);
      await expect(page.getByRole("button", { name: "Raw", exact: true }).first()).toBeVisible();
      await expect(page.getByTitle("Curved score").first()).toBeVisible();
    },
  },

  "course/predictor-none": {
    run: async (page) => {
      await openCourse(
        page,
        course({ assignments: ASGS.filter((a) => a.points_earned !== null) }),
      );
      await text(page, "Predict your grade by adding an unscored assignment.");
    },
  },

  "course/predictor-collapsed": {
    run: async (page) => {
      await openCourse(page, course());
      await expect(page.getByRole("button", { name: /Predict My Grade/ })).toBeVisible();
    },
  },

  "course/predictor-open": {
    run: async (page) => {
      await openCourse(page, course());
      await page.getByRole("button", { name: /Predict My Grade/ }).click();
      await text(page, "Hypothetical Scores");
      await expect(page.locator(".chip--accent", { hasText: "Predicted" })).toBeVisible();
    },
  },

  "course/predictor-missing-total": {
    run: async (page) => {
      await openCourse(
        page,
        course({
          assignments: [...ASGS, asg("fig-a-quiz", "Pop quiz (points TBA)", "fig-cat-exam", null, null, null)],
        }),
      );
      await page.getByRole("button", { name: /Predict My Grade/ }).click();
      await text(page, "⚠ No Total Score");
    },
  },

  "course/predictor-curved": {
    run: async (page) => {
      await openCourse(page, CURVED);
      await page.getByRole("button", { name: /Predict My Grade/ }).click();
      await text(page, "Hypothetical Scores");
      // Topbar has its own Raw/Curved pill; the predictor's is the last one.
      await page.getByRole("button", { name: "Curved", exact: true }).last().click();
      await text(page, "Bell Curve:");
      await text(page, "✓ Curve Active");
    },
  },

  "course/assignment-new": {
    run: async (page) => {
      await openCourse(page);
      await page.getByTestId("gradebook-add-assignment").click();
      await expect(page.getByRole("dialog", { name: "New Assignment" })).toBeVisible();
      await visible(page, "gradebook-assignment-title");
    },
  },

  "course/assignment-title-required": {
    run: async (page) => {
      await openCourse(page);
      await page.getByTestId("gradebook-add-assignment").click();
      await page.getByTestId("gradebook-assignment-title").focus();
      await dialog(page).getByLabel("Notes").click();
      await expect(dialog(page).getByText("Required", { exact: true })).toBeVisible();
      await expect(page.getByTestId("gradebook-assignment-save")).toBeDisabled();
    },
  },

  "course/assignment-invalid-date": {
    run: async (page) => {
      await openCourse(
        page,
        course({ assignments: [...ASGS, asg("fig-a-bad", "Reading response", "fig-cat-hw", null, 10, "2026-02-30")] }),
      );
      await page.getByRole("button", { name: /Reading response/ }).click();
      await expect(page.getByRole("dialog", { name: "Edit Assignment" })).toBeVisible();
      await expect(dialog(page).getByText("Invalid date")).toBeVisible();
    },
  },

  "course/assignment-curve-expanded": {
    run: async (page) => {
      await openCourse(page);
      await page.getByTestId("gradebook-add-assignment").click();
      await dialog(page).getByRole("button", { name: /Bell Curve/ }).click();
      await expect(dialog(page).getByText(/A bell curve adjusts your score/)).toBeVisible();
    },
  },

  "course/assignment-edit": {
    run: async (page) => {
      await openCourse(page, course());
      await page.getByRole("button", { name: /Problem Set 1/ }).click();
      await expect(page.getByRole("dialog", { name: "Edit Assignment" })).toBeVisible();
      await expect(dialog(page).getByRole("button", { name: "Delete" })).toBeVisible();
    },
  },

  "course/assignment-saving": {
    run: async (page) => {
      await hold(page, "/api/gradebook/assignments", "POST");
      await openCourse(page);
      await page.getByTestId("gradebook-add-assignment").click();
      await page.getByTestId("gradebook-assignment-title").fill("Problem Set 5");
      await page.getByTestId("gradebook-assignment-save").click();
      await expect(page.getByTestId("gradebook-assignment-save")).toHaveText("Saving…");
    },
  },

  "course/assignment-save-error": {
    run: async (page) => {
      await pinTimers(page, TOASTS);
      await mockError(page, "/api/gradebook/assignments", 500, "Couldn't save the assignment. Try again.", "POST");
      await openCourse(page);
      await page.getByTestId("gradebook-add-assignment").click();
      await page.getByTestId("gradebook-assignment-title").fill("Problem Set 5");
      await page.getByTestId("gradebook-assignment-save").click();
      await expect(page.getByRole("status").filter({ hasText: /save/i }).first()).toBeVisible();
      await expect(page.getByRole("dialog", { name: "New Assignment" })).toBeVisible();
    },
  },

  "course/edit-weights": {
    run: async (page) => {
      await openCourse(page, course());
      await page.getByRole("button", { name: "Edit Weights" }).click();
      await expect(page.getByRole("dialog", { name: "Edit categories & weights" })).toBeVisible();
      await expect(dialog(page).getByText(/Total: 100\.0% ✓/)).toBeVisible();
    },
  },

  "course/edit-weights-invalid": {
    run: async (page) => {
      await openCourse(page, course());
      await page.getByRole("button", { name: "Edit Weights" }).click();
      const firstWeight = dialog(page).locator('input[type="number"][max="100"]').first();
      await firstWeight.fill("45");
      await expect(dialog(page).getByText(/need 100%/)).toBeVisible();
    },
  },

  "course/edit-weights-dragover": {
    run: async (page) => {
      await openCourse(page, course());
      await page.getByRole("button", { name: "Edit Weights" }).click();
      const rows = dialog(page).locator("li[draggable]");
      await expect(rows).toHaveCount(4);
      await rows.nth(0).dispatchEvent("dragstart");
      await rows.nth(2).dispatchEvent("dragover");
      await expect(rows.nth(2)).toHaveAttribute("style", /outline: 2px solid/);
    },
  },

  "course/letter-scale": {
    run: async (page) => {
      await openCourse(page);
      await page.getByRole("button", { name: "Letter Scale" }).click();
      await expect(page.getByRole("dialog", { name: "Letter scale" })).toBeVisible();
    },
  },

  "course/letter-scale-invalid": {
    run: async (page) => {
      await openCourse(page);
      await page.getByRole("button", { name: "Letter Scale" }).click();
      await dialog(page).locator('input[type="number"]').first().fill("10");
      await expect(dialog(page).getByText("Tiers must be sorted descending by minimum.")).toBeVisible();
    },
  },

  "course/curve-settings": {
    run: async (page) => {
      await openCourse(page);
      await page.getByTitle("Bell curve policy").click();
      await text(page, "Bell Curve Settings");
    },
  },
};

const gradescope: RecipeBook = {
  "gs/loading": {
    run: async (page) => {
      await hold(page, "/api/gradescope/status");
      await openGsModal(page);
      await expect(page.getByRole("dialog").getByText("Loading…")).toBeVisible();
    },
  },

  "gs/choose-mode": {
    run: async (page) => {
      await mockJson(page, "/api/gradescope/status", { has_credentials: false, auth_mode: null, last_synced_at: null });
      await openGsModal(page);
      await expect(page.getByRole("heading", { name: "Connect Gradescope" })).toBeVisible();
    },
  },

  "gs/credentials": {
    run: async (page) => {
      await mockJson(page, "/api/gradescope/status", { has_credentials: false, auth_mode: null, last_synced_at: null });
      await openGsModal(page);
      await page.getByRole("button", { name: /Email \+ password/ }).click();
      await expect(page.getByRole("heading", { name: "Sign in with Gradescope password" })).toBeVisible();
    },
  },

  "gs/cookies": {
    run: async (page) => {
      await mockJson(page, "/api/gradescope/status", { has_credentials: false, auth_mode: null, last_synced_at: null });
      await openGsModal(page);
      await page.getByRole("button", { name: /Session cookies \(manual\)/ }).click();
      await expect(page.getByRole("heading", { name: "Paste your Gradescope session" })).toBeVisible();
    },
  },

  "gs/bu-sso-form": {
    run: async (page) => {
      await mockJson(page, "/api/gradescope/status", { has_credentials: false, auth_mode: null, last_synced_at: null });
      await openGsModal(page);
      await page.getByRole("button", { name: /BU SSO \+ Duo/ }).click();
      await expect(page.getByRole("heading", { name: "Sign in with BU SSO" })).toBeVisible();
    },
  },

  "gs/bu-sso-waiting": {
    run: async (page) => {
      await mockJson(page, "/api/gradescope/status", { has_credentials: false, auth_mode: null, last_synced_at: null });
      await hold(page, "/api/gradescope/credentials/bu-sso", "POST");
      await openGsModal(page);
      await page.getByRole("button", { name: /BU SSO \+ Duo/ }).click();
      await page.getByLabel("BU username").fill("mellis");
      await page.getByRole("dialog").locator('input[type="password"]').fill("not-a-real-password");
      await page.getByRole("button", { name: /Sign in & send Duo push/ }).click();
      await expect(page.getByRole("heading", { name: "Waiting for Duo approval" })).toBeVisible();
    },
  },

  "gs/link": {
    run: async (page) => {
      await gsUnlinked(page);
      await openGsModal(page);
      await expect(page.getByRole("heading", { name: "Pick the matching Gradescope course" })).toBeVisible();
      await expect(page.getByRole("button", { name: /MA 210/ })).toBeVisible();
    },
  },

  "gs/link-empty": {
    run: async (page) => {
      await gsUnlinked(page, { courses: [] });
      await openGsModal(page);
      await text(page, /We didn.t find any student courses/);
    },
  },

  "gs/ready": {
    run: async (page) => {
      await openGsReady(page);
      await expect(page.getByRole("button", { name: "Sync now" })).toBeVisible();
    },
  },

  "gs/syncing": {
    run: async (page) => {
      await hold(page, "/api/gradescope/sync/", "POST");
      await openGsReady(page);
      await page.getByRole("button", { name: "Sync now" }).click();
      await expect(page.getByRole("dialog").getByRole("button", { name: "Syncing…" })).toBeVisible();
    },
  },

  "gs/done": {
    run: async (page) => {
      await mockJson(page, "/api/gradescope/sync/", { inserted: 4, updated: 7, skipped: 2, failed: 0 }, { method: "POST" });
      await openGsReady(page);
      await page.getByRole("button", { name: "Sync now" }).click();
      await expect(page.getByRole("heading", { name: "Sync complete" })).toBeVisible();
    },
  },

  "gs/done-partial": {
    run: async (page) => {
      await mockJson(page, "/api/gradescope/sync/", { inserted: 3, updated: 5, skipped: 1, failed: 2 }, { method: "POST" });
      await openGsReady(page);
      await page.getByRole("button", { name: "Sync now" }).click();
      await expect(page.getByRole("heading", { name: "Sync needs attention" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Retry sync" })).toBeVisible();
    },
  },

  "gs/error-banner": {
    run: async (page) => {
      await mockJson(page, "/api/gradescope/status", { has_credentials: false, auth_mode: null, last_synced_at: null });
      await mockError(page, "/api/gradescope/credentials", 400, "Invalid Gradescope credentials", "POST");
      await openGsModal(page);
      await page.getByRole("button", { name: /Email \+ password/ }).click();
      await page.getByRole("dialog").getByLabel("Email", { exact: true }).fill("maya.ellis@example.edu");
      await page.getByRole("dialog").locator('input[type="password"]').fill("not-a-real-password");
      await page.getByRole("button", { name: "Connect", exact: true }).click();
      await expect(page.getByRole("dialog").getByRole("alert")).toBeVisible();
    },
  },

  "gs/verification-error": {
    run: async (page) => {
      await mockJson(page, "/api/gradescope/status", GS_CONNECTED);
      await mockJson(page, "/api/gradescope/links", { links: [] });
      await mockError(page, "/api/gradescope/courses", 502, "Gradescope login timed out");
      await openGsModal(page);
      await expect(page.getByRole("heading", { name: "Couldn't verify Gradescope" })).toBeVisible();
    },
  },
};

const calendar: RecipeBook = {
  "calendar/loading": {
    run: async (page) => {
      await hold(page, "/api/calendar/all/");
      await page.goto("/calendar");
      await text(page, /0 assignments/);
    },
  },

  "calendar/error": {
    run: async (page) => {
      await mockError(page, "/api/calendar/all/");
      await page.goto("/calendar");
      await visible(page, "calendar-load-error");
    },
  },

  "calendar/refresh-error-toast": {
    run: async (page) => {
      await pinTimers(page, TOASTS);
      let failing = false;
      await page.route(
        (url) => url.pathname.includes("/api/calendar/all/"),
        async (route) => {
          if (!failing) await route.fulfill({ json: { assignments: CAL_ITEMS } });
          else await route.fulfill({ status: 500, json: { detail: "Internal Server Error" } });
        },
      );
      await mockJson(page, "/api/calendar/assignments/", { updated: true }, { method: "PATCH" });
      await calendarReady(page);
      await page.getByRole("button", { name: "Table", exact: true }).click();
      await page.getByTitle("Edit").first().click();
      failing = true; // the post-save reload is the one that fails
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await text(page, /Couldn't refresh the calendar/);
    },
  },

  "calendar/month": {
    run: async (page) => {
      await calendarReady(page);
      await text(page, /March 2026/);
    },
  },

  "calendar/month-empty": {
    run: async (page) => {
      await mockJson(page, "/api/calendar/all/", { assignments: [] });
      await calendarReady(page);
      await text(page, /0 assignments/);
    },
  },

  "calendar/week": {
    run: async (page) => {
      await calendarReady(page);
      await page.getByRole("button", { name: "Week", exact: true }).click();
      await text(page, /Mar 9 – Mar 15/);
    },
  },

  "calendar/day": {
    run: async (page) => {
      await calendarReady(page);
      await page.getByRole("button", { name: "Day", exact: true }).click();
      await text(page, /Mar 11, 2026/);
    },
  },

  "calendar/table": {
    run: async (page) => {
      await mockJson(page, "/api/calendar/all/", { assignments: CAL_ITEMS });
      await calendarReady(page);
      await page.getByRole("button", { name: "Table", exact: true }).click();
      await text(page, /0 of 6 selected/);
    },
  },

  "calendar/table-empty": {
    run: async (page) => {
      await mockJson(page, "/api/calendar/all/", { assignments: [] });
      await calendarReady(page);
      await page.getByRole("button", { name: "Table", exact: true }).click();
      await text(page, "No assignments yet.");
    },
  },

  "calendar/table-row-editing": {
    run: async (page) => {
      await mockJson(page, "/api/calendar/all/", { assignments: CAL_ITEMS });
      await calendarReady(page);
      await page.getByRole("button", { name: "Table", exact: true }).click();
      await page.getByTitle("Edit").first().click();
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeVisible();
    },
  },

  "calendar/google-disconnected": {
    run: async (page) => {
      await mockJson(page, "/api/calendar/status/", { connected: false });
      await calendarReady(page);
      await expect(page.getByRole("button", { name: /Connect Google/ })).toBeVisible();
    },
  },

  "calendar/google-connected": {
    run: async (page) => {
      await googleConnected(page);
      await calendarReady(page);
      await expect(page.getByRole("button", { name: /View Google events/ })).toBeVisible();
      await expect(page.getByRole("button", { name: "Disconnect" })).toBeVisible();
    },
  },

  "calendar/google-disconnect-armed": {
    run: async (page) => {
      await pinTimers(page, ARMED);
      await googleConnected(page);
      await calendarReady(page);
      await page.getByRole("button", { name: "Disconnect" }).click();
      await expect(page.getByRole("button", { name: "Click again" })).toBeVisible();
    },
  },

  "calendar/google-events-loading": {
    run: async (page) => {
      await googleConnected(page);
      await hold(page, "/api/calendar/import/");
      await calendarReady(page);
      await page.getByRole("button", { name: /View Google events/ }).click();
      await expect(page.getByRole("button", { name: /Loading…/ })).toBeVisible();
    },
  },

  "calendar/google-events-modal": {
    run: async (page) => {
      await googleConnected(page);
      await mockJson(page, "/api/calendar/import/", GOOGLE_EVENTS);
      await calendarReady(page);
      await page.getByRole("button", { name: /View Google events/ }).click();
      await text(page, "Upcoming Google Calendar events");
      await text(page, "CS101 Office Hours");
    },
  },

  "calendar/google-events-empty": {
    run: async (page) => {
      await googleConnected(page);
      await mockJson(page, "/api/calendar/import/", { events: [], count: 0 });
      await calendarReady(page);
      await page.getByRole("button", { name: /View Google events/ }).click();
      await text(page, "No upcoming events in the next 60 days.");
    },
  },

  "calendar/oauth-return": {
    run: async (page) => {
      await pinTimers(page, TOASTS);
      await googleConnected(page);
      await page.goto("/calendar?connected=true");
      await text(page, "Google Calendar connected");
    },
  },

  "calendar/upload-modal": {
    run: async (page) => {
      await calendarReady(page);
      await page.getByRole("button", { name: /Import syllabus/ }).click();
      await visible(page, "upload-modal");
      await visible(page, "upload-modal-dropzone");
    },
  },

  "calendar/toasts": {
    run: async (page) => {
      await pinTimers(page, TOASTS);
      await googleConnected(page);
      await mockJson(page, "/api/calendar/sync", { synced_count: 4 }, { method: "POST" });
      await calendarReady(page);
      await page.getByRole("button", { name: "Sync", exact: true }).click();
      await text(page, "Synced 4 events to Google.");
    },
  },
};

const planner: RecipeBook = {
  "course-planner/coming-soon": {
    run: async (page) => {
      await page.goto("/course-planner");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });
      await text(page, /Coming soon/i);
    },
  },
};

const achievements: RecipeBook = {
  "achievements/loading": {
    run: async (page) => {
      await hold(page, MY_ACHIEVEMENTS, "GET");
      await page.goto("/achievements");
      await text(page, "0 earned · 0 in progress");
      await visible(page, "achievements-tab-achievements");
    },
  },

  "achievements/populated": {
    run: async (page) => {
      await page.goto("/achievements");
      await visible(page, "gamification-hero");
      await visible(page, "gamification-total-xp");
    },
  },

  "achievements/hero-max-level": {
    run: async (page) => {
      await patchJson(page, /\/api\/gamification\/me/, (b) => ({ ...b, xp_for_level: 0, xp_into_level: 0, level_pct: 100 }));
      await page.goto("/achievements");
      await visible(page, "gamification-hero");
      await text(page, "Highest stage reached");
    },
  },

  "achievements/no-me": {
    run: async (page) => {
      await mockError(page, "/api/gamification/me");
      await achievementsPage(page);
      await expect(page.getByTestId("gamification-hero")).toHaveCount(0);
    },
  },

  "achievements/showcase-empty": {
    run: async (page) => {
      await achievementsPage(page, achievementsBody(false));
      await expect(page.getByText("+ empty slot")).toHaveCount(5);
    },
  },

  "achievements/showcase-filled": {
    run: async (page) => {
      await achievementsPage(page, achievementsBody(true));
      await visible(page, "achievements-showcase-remove-fig-ach-first");
      await expect(page.getByText("+ empty slot")).toHaveCount(2);
    },
  },

  "achievements/badge-earned": {
    run: async (page) => {
      await achievementsPage(page);
      await text(page, /Earned .* · \+50 XP/);
    },
  },

  "achievements/badge-progress": {
    run: async (page) => {
      await achievementsPage(page);
      await text(page, "6 / 10");
    },
  },

  "achievements/badge-locked": {
    run: async (page) => {
      await achievementsPage(page);
      await text(page, "Locked · +200 XP");
    },
  },

  "achievements/badge-secret": {
    run: async (page) => {
      await achievementsPage(page);
      await text(page, "???");
      await page.getByText("???").first().scrollIntoViewIfNeeded();
    },
  },

  "achievements/filter-category": {
    run: async (page) => {
      await achievementsPage(page);
      await page.getByRole("button", { name: /^Social · \d+$/ }).click();
      await expect(page.getByRole("heading", { name: "Social", level: 2 })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Activity", level: 2 })).toHaveCount(0);
    },
  },

  "achievements/grid-empty": {
    run: async (page) => {
      await achievementsPage(page, { earned: [], available: [] });
      await text(page, "No achievements yet.");
    },
  },

  "achievements/badge-modal-earned": {
    run: async (page) => {
      await achievementsPage(page);
      await page.getByRole("button", { name: /Week-Long Streak/ }).click();
      await expect(page.getByRole("dialog", { name: "Week-Long Streak" })).toBeVisible();
    },
  },

  "achievements/badge-modal-progress": {
    run: async (page) => {
      await achievementsPage(page);
      await page.getByRole("button", { name: /Quiz Ace/ }).click();
      await expect(page.getByRole("dialog", { name: "Quiz Ace" })).toBeVisible();
    },
  },

  "achievements/badge-modal-locked": {
    run: async (page) => {
      await achievementsPage(page);
      await page.getByRole("button", { name: /Night Owl/ }).click();
      await expect(page.getByRole("dialog", { name: "Night Owl" })).toBeVisible();
    },
  },

  "achievements/badge-modal-secret": {
    run: async (page) => {
      await achievementsPage(page);
      await page.getByRole("button", { name: /\?\?\?/ }).click();
      await expect(page.getByRole("dialog", { name: "Secret achievement" })).toBeVisible();
    },
  },

  "achievements/toast-unlocked": {
    run: async (page) => {
      await pinTimers(page, TOASTS);
      // A non-empty "seen" set makes every unseen earned badge a fresh unlock.
      await storage(page, { "ach:seen-ids": JSON.stringify(["fig-ach-first", "fig-ach-streak"]) });
      await achievementsPage(page);
      await text(page, "Achievement unlocked: Study Buddy");
    },
  },

  "achievements/toast-save-error": {
    run: async (page) => {
      await pinTimers(page, TOASTS);
      await mockError(page, "/featured-achievements", 500, "Internal Server Error", "POST");
      await achievementsPage(page, achievementsBody(true));
      await page.getByTestId("achievements-showcase-remove-fig-ach-buddy").click();
      await text(page, /Couldn't save showcase/);
    },
  },

  "achievements/leaderboard-loading": {
    run: async (page) => {
      await leaderboard(page, "hold");
      await text(page, "Loading leaderboard…");
    },
  },

  "achievements/leaderboard-populated": {
    run: async (page) => {
      await leaderboard(page, { rows: LB_ROWS, you: LB_ROWS[1], resets_at: "2026-03-16T00:00:00Z" });
      await visible(page, "leaderboard-row-you");
    },
  },

  "achievements/leaderboard-podium-partial": {
    run: async (page) => {
      await leaderboard(page, { rows: LB_ROWS.slice(0, 2), you: LB_ROWS[1], resets_at: "2026-03-16T00:00:00Z" });
      await visible(page, "leaderboard-row-you");
      await text(page, "Priya Raman");
    },
  },

  "achievements/leaderboard-empty": {
    run: async (page) => {
      await leaderboard(page, { rows: [], you: null, resets_at: "2026-03-16T00:00:00Z" });
      await text(page, "No XP earned in this group yet this week.");
    },
  },

  "achievements/leaderboard-error": {
    run: async (page) => {
      await leaderboard(page, "error");
      await text(page, /Couldn.t load the leaderboard right now\./);
    },
  },

  "achievements/leaderboard-viewer-outside": {
    run: async (page) => {
      const rows = LB_ROWS.filter((r) => !r.is_you).map((r, i) => ({ ...r, rank: i + 1 }));
      await leaderboard(page, { rows, you: lbRow(14, ME, "Maya Ellis", 85, true), resets_at: "2026-03-16T00:00:00Z" });
      await visible(page, "leaderboard-row-you");
      await expect(page.getByTestId("leaderboard-row-you")).toContainText("14");
    },
  },

  "achievements/activity-loading": {
    run: async (page) => {
      await activity(page, "hold");
      await text(page, "Loading activity…");
    },
  },

  "achievements/activity-populated": {
    run: async (page) => {
      await activity(page, ACTIVITY);
      await expect(page.getByTestId("activity-week-total")).toContainText("195 XP");
    },
  },

  "achievements/activity-zero-week": {
    run: async (page) => {
      await activity(page, {
        ...ACTIVITY,
        week: ACTIVITY.week.map((d) => ({ ...d, xp: 0 })),
        tiles: { week_total: 0, daily_avg: 0, best_day: 0, best_day_label: "", streak: 0 },
      });
      await text(page, /No XP earned this week yet/);
    },
  },

  "achievements/activity-error": {
    run: async (page) => {
      await activity(page, "error");
      await text(page, /Couldn.t load activity right now\./);
    },
  },

  "global/achievement-unlock-toast": {
    run: async (page) => {
      await pinTimers(page, TOASTS);
      const body = achievementsBody(false);
      let calls = 0;
      let unlocked = false;
      await page.route(urlMatches(MY_ACHIEVEMENTS), async (route) => {
        if (route.request().method() !== "GET") return route.fallback();
        calls += 1;
        // Answers before `unlocked` prime the watcher; later ones carry a new badge.
        await route.fulfill({ json: unlocked ? body : { ...body, earned: body.earned.slice(0, 2) } });
      });
      await page.goto("/gradebook");
      await visible(page, "gradebook-transcript-open");
      await expect.poll(() => calls, { timeout: 30_000 }).toBeGreaterThan(0);
      await page.waitForTimeout(1_000);
      unlocked = true;
      await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
      await text(page, "Achievement unlocked");
      await text(page, "Study Buddy");
    },
  },
};

const social: RecipeBook = {
  "social/loading": {
    run: async (page) => {
      await hold(page, MY_ROOMS, "GET");
      await hold(page, MY_FRIENDS, "GET");
      await page.goto("/social");
      await text(page, "Select or create a room to begin.");
      await visible(page, "social-create-room");
    },
  },

  "social/no-rooms": {
    run: async (page) => {
      await mockJson(page, MY_ROOMS, { rooms: [] }, { method: "GET" });
      await page.goto("/social");
      await text(page, /No rooms yet/);
    },
  },

  "social/room-chat": {
    run: async (page) => {
      await studyRoom(page);
      await visible(page, "social-chat-messages");
      await visible(page, "social-chat-input");
    },
  },

  "social/chat-empty": {
    run: async (page) => {
      await studyRoom(page, { messages: [], has_more: false });
      await text(page, "No messages yet — say hi.");
    },
  },

  "social/chat-has-more": {
    run: async (page) => {
      await studyRoom(page, { messages: STUDY_MSGS, has_more: true });
      await visible(page, "social-chat-load-earlier");
    },
  },

  "social/chat-message-menu": {
    run: async (page) => {
      await studyChat(page);
      await openBubbleMenu(page, "fig-msg-2", "I keep tripping");
      await visible(page, "social-chat-message-edit");
    },
  },

  "social/chat-emoji-picker": {
    run: async (page) => {
      await studyChat(page);
      await openBubbleMenu(page, "fig-msg-2", "I keep tripping");
      await page.getByTestId("social-chat-message-react").click();
      await visible(page, "social-chat-emoji-👍");
    },
  },

  "social/chat-reactions": {
    run: async (page) => {
      await studyChat(page);
      await visible(page, "social-chat-reaction-🎉");
    },
  },

  "social/chat-replying": {
    run: async (page) => {
      await studyChat(page);
      await openBubbleMenu(page, "fig-msg-6", "pair on the tree problems");
      await page.getByTestId("social-chat-message-reply").click();
      await visible(page, "social-chat-reply-cancel");
      await text(page, /Replying to/);
    },
  },

  "social/chat-editing": {
    run: async (page) => {
      await studyChat(page);
      await openBubbleMenu(page, "fig-msg-2", "I keep tripping");
      await page.getByTestId("social-chat-message-edit").click();
      await visible(page, "social-chat-edit-input");
    },
  },

  "social/chat-deleted-message": {
    run: async (page) => {
      await studyChat(page);
      await expect(page.getByTestId("social-chat-message-fig-msg-3")).toContainText("Message deleted");
    },
  },

  "social/chat-edited": {
    run: async (page) => {
      await studyChat(page);
      await expect(page.getByTestId("social-chat-message-fig-msg-5")).toContainText("(edited)");
    },
  },

  "social/chat-image": {
    run: async (page) => {
      await studyChat(page);
      await expect(page.getByTestId("social-chat-message-fig-msg-4").getByRole("img", { name: "attachment" })).toBeVisible();
    },
  },

  "social/chat-mention-popup": {
    run: async (page) => {
      await studyChat(page);
      await page.getByTestId("social-chat-input").fill("@");
      await visible(page, `social-chat-mention-${SECOND}`);
    },
  },

  "social/overview-loading": {
    run: async (page) => {
      await hold(page, ROOM_OVERVIEW, "GET");
      await studyRoom(page);
      await roomTab(page, "Overview");
      await expect(page.getByText("Loading…").first()).toBeVisible();
    },
  },

  "social/overview": {
    run: async (page) => {
      await studyRoom(page);
      await roomTab(page, "Overview");
      await text(page, "AI room summary");
      await visible(page, `social-member-kick-${SECOND}`);
    },
  },

  "social/overview-non-owner": {
    run: async (page) => {
      await page.goto("/social");
      await page.getByTestId(`social-room-item-${ROOM_LOUNGE}`).click({ timeout: 30_000 });
      await roomTab(page, "Overview");
      await visible(page, `social-member-${SECOND}`);
      await expect(page.getByTestId(`social-member-kick-${SECOND}`)).toHaveCount(0);
    },
  },

  "social/overview-leave-armed": {
    run: async (page) => {
      await pinTimers(page, ARMED);
      await studyRoom(page);
      await roomTab(page, "Overview");
      await page.getByTestId("social-room-leave").click();
      await expect(page.getByTestId("social-room-leave")).toContainText("Click again");
    },
  },

  "social/overview-kick-armed": {
    run: async (page) => {
      await pinTimers(page, ARMED);
      await studyRoom(page);
      await roomTab(page, "Overview");
      await page.getByTestId(`social-member-kick-${SECOND}`).click();
      await expect(page.getByTestId(`social-member-kick-${SECOND}`)).toHaveText("Click again");
    },
  },

  "social/overview-comparison": {
    run: async (page) => {
      await mockJson(page, ROOM_OVERVIEW, OVERVIEW_COMPARE, { method: "GET" });
      await page.goto(`/social?suggest=${SECOND}`);
      await text(page, "Comparison with Jordan Lee");
    },
  },

  "social/match-idle": {
    run: async (page) => {
      await studyRoom(page);
      await roomTab(page, "Study match");
      await text(page, "Find your study match");
      await visible(page, "social-match-run");
    },
  },

  "social/match-results": {
    run: async (page) => {
      await pinTimers(page, TOASTS);
      await mockJson(
        page,
        `/api/social/rooms/${ROOM_STUDY}/match`,
        {
          matches: [
            { partner: { id: SECOND, name: "Jordan Lee" }, compatibility_score: 0.86, summary: "Strong on recursion and trees where you're still building; you can return the favour on big-O." },
            { partner: { id: "fig-u-priya", name: "Priya Raman" }, compatibility_score: 0.71, summary: "Similar pace through the course, complementary gaps in loops and sorting." },
          ],
        },
        { method: "POST" },
      );
      await studyRoom(page);
      await roomTab(page, "Study match");
      await page.getByTestId("social-match-run").click();
      await text(page, "Suggested partners");
      await text(page, /Best match: Jordan Lee at 86%/);
    },
  },

  "social/activity": {
    run: async (page) => {
      await mockJson(page, `/api/social/rooms/${ROOM_STUDY}/activity`, {
        activities: [
          { id: "fig-act-1", user_name: "Jordan Lee", activity_type: "mastered", concept_name: "Binary Trees", created_at: "2026-03-11T13:40:00Z" },
          { id: "fig-act-2", user_name: "Maya Ellis", activity_type: "started learning", concept_name: "Recursion", created_at: "2026-03-11T11:05:00Z" },
          { id: "fig-act-3", user_name: "Jordan Lee", activity_type: "quizzed on", concept_name: "Big-O Notation", created_at: "2026-03-10T20:15:00Z" },
        ],
      });
      await studyRoom(page);
      await roomTab(page, "Activity");
      await text(page, "Binary Trees");
    },
  },

  "social/directory-loading": {
    run: async (page) => {
      await hold(page, "/api/social/students");
      await page.goto("/social");
      await page.getByTestId("social-directory-open").click({ timeout: 30_000 });
      await text(page, "Loading directory…");
    },
  },

  "social/directory-list": {
    run: async (page) => {
      await page.goto("/social");
      await page.getByTestId("social-directory-open").click({ timeout: 30_000 });
      await text(page, "Students at your school");
      await expect(page.locator(`a[href="/profile/${SECOND}"]`).first()).toBeVisible({ timeout: 30_000 });
    },
  },

  "social/directory-no-match": {
    run: async (page) => {
      await page.goto("/social");
      await page.getByTestId("social-directory-open").click({ timeout: 30_000 });
      await expect(page.locator(`a[href="/profile/${SECOND}"]`).first()).toBeVisible({ timeout: 30_000 });
      await page.getByTestId("social-directory-search").fill("zzqx nobody");
      await text(page, "No matches.");
    },
  },

  "social/create-form": {
    run: async (page) => {
      await page.goto("/social");
      await page.getByTestId("social-create-room").click({ timeout: 30_000 });
      await visible(page, "social-create-topic");
      await visible(page, "social-create-public");
    },
  },

  "social/join-form": {
    run: async (page) => {
      await page.goto("/social");
      await page.getByTestId("social-join-room").click({ timeout: 30_000 });
      await expect(page.getByTestId("social-create-join-input")).toHaveAttribute("placeholder", "Invite code");
    },
  },

  "social/public-rooms-list": {
    run: async (page) => {
      await mockJson(page, "/api/social/public-rooms", PUBLIC_ROOMS, { method: "GET" });
      await page.goto("/social");
      await visible(page, "social-public-join-fig-room-pub-1");
    },
  },

  "social/room-item-public": {
    run: async (page) => {
      await patchJson(page, MY_ROOMS, (b) => ({
        ...b,
        rooms: ((b.rooms as Record<string, unknown>[]) ?? []).map((r) =>
          r.id === ROOM_STUDY ? { ...r, is_public: true, topic: "Midterm prep" } : r,
        ),
      }));
      await page.goto("/social");
      await expect(page.getByTestId(`social-room-item-${ROOM_STUDY}`).getByText("Public", { exact: true })).toBeVisible({
        timeout: 30_000,
      });
    },
  },

  "social/friends-empty": {
    run: async (page) => {
      await socialFriends(page, []);
      await text(page, "No friends yet.");
    },
  },

  "social/friends-incoming": {
    run: async (page) => {
      await socialFriends(
        page,
        [],
        [{ id: "fig-fr-in-1", from_user_id: "fig-u-priya", name: "Priya Raman", created_at: "2026-03-10T18:00:00Z" }],
      );
      await visible(page, "social-friend-accept-fig-fr-in-1");
    },
  },

  "social/friends-outgoing": {
    run: async (page) => {
      await socialFriends(
        page,
        [],
        [],
        [{ id: "fig-fr-out-1", to_user_id: "fig-u-sam", name: "Sam Okafor", created_at: "2026-03-09T18:00:00Z" }],
      );
      await visible(page, "social-friend-outgoing-fig-fr-out-1");
    },
  },

  "social/friends-list": {
    run: async (page) => {
      await socialFriends(page, [friend(SECOND, "Jordan Lee", 7, 2140), friend("fig-u-priya", "Priya Raman", 9, 3380)]);
      await visible(page, `social-friend-row-${SECOND}`);
      await text(page, "Lv 7 · 2140 XP");
    },
  },

  "social/remove-armed": {
    run: async (page) => {
      await pinTimers(page, ARMED);
      await socialFriends(page, [friend(SECOND, "Jordan Lee", 7, 2140), friend("fig-u-priya", "Priya Raman", 9, 3380)]);
      await page.getByTestId(`social-friend-remove-${SECOND}`).click();
      await expect(page.getByTestId(`social-friend-remove-${SECOND}`)).toHaveText("Click again");
    },
  },

  "social/invite-copied": {
    run: async (page) => {
      await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
      await pinTimers(page, [2000, ...TOASTS]);
      await studyRoom(page);
      await page.getByTestId("social-invite-copy").click();
      await expect(page.getByTestId("social-invite-copy")).toHaveText("Copied!");
    },
  },

  "social/toasts": {
    run: async (page) => {
      await pinTimers(page, TOASTS);
      await mockJson(page, "/api/social/rooms/create", { room_id: "fig-room-new", invite_code: "FIG-NEW1" }, { method: "POST" });
      await page.goto("/social");
      await page.getByTestId("social-create-room").click({ timeout: 30_000 });
      await page.getByTestId("social-create-join-input").fill("Recursion Review Crew");
      await page.getByTestId("social-create-join-submit").click();
      await text(page, "Room created");
    },
  },
};

const profile: RecipeBook = {
  "profile/loading": {
    run: async (page) => {
      await hold(page, SECOND_PROFILE, "GET");
      await page.goto(`/profile/${SECOND}`);
      await text(page, "Loading…");
    },
  },

  "profile/error": {
    run: async (page) => {
      await mockError(page, SECOND_PROFILE, 404, "Profile not found", "GET");
      await page.goto(`/profile/${SECOND}`);
      await text(page, /Couldn.t load this profile\./);
    },
  },

  "profile/other-populated": {
    run: async (page) => {
      await page.goto(`/profile/${SECOND}`);
      await visible(page, "profile-add-friend");
    },
  },

  "profile/other-add-friend": {
    run: async (page) => {
      await profileOf(page);
      await expect(page.getByTestId("profile-add-friend")).toContainText("Add friend", { timeout: 30_000 });
    },
  },

  "profile/other-pending": {
    run: async (page) => {
      await profileOf(page, [], [{ id: "fig-fr-out", to_user_id: SECOND, name: "Jordan Lee", created_at: "2026-03-10T18:00:00Z" }]);
      await expect(page.getByTestId("profile-add-friend")).toHaveText("Request sent", { timeout: 30_000 });
    },
  },

  "profile/other-friends": {
    run: async (page) => {
      await profileOf(page, [friend(SECOND, "Jordan Lee", 7, 2140)]);
      await expect(page.getByTestId("profile-friend-status")).toHaveText("Friends", { timeout: 30_000 });
    },
  },

  "profile/friend-status-loading": {
    run: async (page) => {
      await hold(page, MY_FRIENDS, "GET");
      await page.goto(`/profile/${SECOND}`);
      await expect(page.getByRole("heading").first()).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("profile-add-friend")).toHaveCount(0);
      await expect(page.getByTestId("profile-friend-status")).toHaveCount(0);
    },
  },

  "profile/own": {
    run: async (page) => {
      await page.goto(`/profile/${ME}`);
      await expect(page.getByText(/-day streak|This profile is private\./).first()).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("profile-add-friend")).toHaveCount(0);
    },
  },

  "profile/banner": {
    run: async (page) => {
      await mockJson(
        page,
        SECOND_PROFILE,
        profileBody({
          equipped_cosmetics: {
            banner: { id: "fig-cos-banner", type: "banner", name: "Golden Hour", slug: "golden-hour", asset_url: "/cosmetics/golden-hour.png", css_value: "#e8a54b", rarity: "epic" },
          },
        }),
        { method: "GET" },
      );
      await profileOf(page);
      await text(page, "Fields of study");
    },
  },

  "profile/private": {
    run: async (page) => {
      await mockJson(page, SECOND_PROFILE, profileBody({ stats: {}, bio: null, majors: [], minors: [] }), { method: "GET" });
      await profileOf(page);
      await text(page, "This profile is private.");
    },
  },

  "profile/minimal": {
    run: async (page) => {
      await mockJson(
        page,
        SECOND_PROFILE,
        profileBody({
          username: null,
          bio: null,
          location: null,
          year: null,
          school: null,
          majors: [],
          minors: [],
          stats: { streak_count: 0, session_count: 0, documents_count: 0, achievements_count: 0 },
        }),
        { method: "GET" },
      );
      await profileOf(page);
      await text(page, /0.*-day streak/);
    },
  },
};

const manageCourses: RecipeBook = {
  "manage-courses/open-all": {
    run: async (page) => {
      await openManageCourses(page);
      await text(page, "All semesters");
    },
  },

  "manage-courses/term-selected": {
    run: async (page) => {
      await openManageCourses(page);
      await page.getByRole("button", { name: "Fall 2025", exact: true }).click();
      await text(page, "BIO110");
      await expect(page.getByText("No courses in this semester yet.")).toHaveCount(0);
    },
  },

  "manage-courses/no-terms": {
    run: async (page) => {
      await patchJson(
        page,
        MY_COURSES,
        (b) => ({
          ...b,
          courses: ((b.courses as Record<string, unknown>[]) ?? []).map((c) => ({ ...c, term: "", terms: [] })),
        }),
      );
      await openManageCourses(page);
      await text(page, /No semesters yet/);
    },
  },

  "manage-courses/term-empty": {
    run: async (page) => {
      await storage(page, { sapling_active_semester: "Spring 2027" });
      await openManageCourses(page);
      await text(page, "No courses in this semester yet.");
    },
  },

  "manage-courses/search-loading": {
    run: async (page) => {
      await hold(page, "/api/onboarding/courses");
      await openManageCourses(page);
      await text(page, "Searching…");
    },
  },

  "manage-courses/no-matches": {
    run: async (page) => {
      await mockJson(page, "/api/onboarding/courses", { courses: [] });
      await openManageCourses(page);
      await page.getByLabel("Search courses").fill("ZZZ 999");
      await text(page, "No matches.");
    },
  },

  "manage-courses/result-states": {
    run: async (page) => {
      await mockJson(page, "/api/onboarding/courses", SEARCH_RESULTS);
      await hold(page, MY_COURSES, "POST");
      await openManageCourses(page);
      await text(page, /Already taken/);
      await page.getByRole("button", { name: "Add", exact: true }).first().click();
      await expect(page.getByRole("button", { name: "Adding…" })).toBeVisible();
    },
  },

  "manage-courses/color-invalid": {
    run: async (page) => {
      await openManageCourses(page);
      const colorInput = page.locator("input.mono").first();
      await colorInput.fill("#zz12");
      await expect(colorInput).toHaveAttribute("style", /var\(--err\)/);
    },
  },

  "manage-courses/delete-armed": {
    run: async (page) => {
      await pinTimers(page, ARMED);
      await openManageCourses(page);
      await page.getByTitle("Remove course").first().click();
      await expect(page.getByTitle("Click again to confirm")).toBeVisible();
    },
  },

  "manage-courses/toasts": {
    run: async (page) => {
      await pinTimers(page, TOASTS);
      await mockJson(page, "/api/onboarding/courses", SEARCH_RESULTS);
      await mockJson(page, MY_COURSES, { course_id: "fig-cat-math242", already_existed: false }, { method: "POST" });
      await openManageCourses(page);
      await page.getByRole("button", { name: "Add", exact: true }).first().click();
      await text(page, "Added MATH242");
    },
  },
};

export const RECIPES_GRADES: RecipeBook = {
  ...gradebook,
  ...coursePage,
  ...gradescope,
  ...calendar,
  ...planner,
  ...achievements,
  ...social,
  ...profile,
  ...manageCourses,
} satisfies Record<string, Recipe>;
