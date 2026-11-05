import { expect, type Page } from "@playwright/test";

import {
  COURSE_CS101,
  NODE_RECURSION,
  SESSION_RECURSION,
  hold,
  mockError,
  mockJson,
  storage,
  text,
  visible,
} from "../helpers";
import type { RecipeBook } from "../types";

/**
 * 01 — dashboard / learn / tree / shared graph
 * (docs/figma/inventory/01-dashboard-learn-tree.md).
 *
 * Nothing here persists: every mutating endpoint a recipe touches (session
 * delete/rename, course color/delete, node add/delete, chat turns, mode
 * switch, end session) is mocked, and chat turns run over an in-page fake SSE
 * stream (`fakeStream`) so no message reaches the backend.
 */

// ── URL patterns (matched against pathname + search) ─────────────────────
const GRAPH = /^\/api\/graph\/[^/]+(\?.*)?$/;
const COURSES = /^\/api\/graph\/[^/]+\/courses$/;
const COURSE_COLOR = /^\/api\/graph\/[^/]+\/courses\/[^/]+\/color$/;
const COURSE_ITEM = /^\/api\/graph\/[^/]+\/courses\/[^/]+$/;
const RECS = /^\/api\/graph\/[^/]+\/recommendations/;
const NODES = /^\/api\/graph\/[^/]+\/nodes$/;
const NODE_ITEM = /^\/api\/graph\/[^/]+\/nodes\/[^/]+$/;
const SESSIONS_LIST = /^\/api\/learn\/sessions\/[^/]+\?limit=/;
const SESSION_ITEM = /^\/api\/learn\/sessions\/[^/]+(\?user_id=.*)?$/;
const RESUME = /^\/api\/learn\/sessions\/[^/]+\/resume$/;
const UPCOMING = /^\/api\/calendar\/upcoming\//;
const CHECKLIST = /^\/api\/topic-checklist\/[^/]+\/courses\/[^/]+(\?.*)?$/;
const CHECKLIST_REFRESH = /^\/api\/topic-checklist\/[^/]+\/courses\/[^/]+\/refresh(\?.*)?$/;
const ATTEMPTS = /^\/api\/quiz\/attempts\?/;
const ONBOARDING_SEARCH = /^\/api\/onboarding\/courses/;

const EMPTY_GRAPH = {
  nodes: [],
  edges: [],
  stats: { streak: 0, mastered: 0, total_nodes: 0, learning: 0, struggling: 0, unexplored: 0 },
};

// ── Local helpers ──────────────────────────────────────────────────────────

/** Fetch the REAL response and rewrite its JSON before the page sees it. */
async function patchJson<T = any>( // eslint-disable-line @typescript-eslint/no-explicit-any
  page: Page,
  pattern: RegExp,
  fn: (body: T) => T | void,
  method = "GET",
): Promise<void> {
  await page.route(
    (url) => pattern.test(url.pathname + url.search),
    async (route) => {
      if (route.request().method() !== method) return route.fallback();
      const res = await route.fetch();
      const body = (await res.json()) as T;
      const out = fn(body) ?? body;
      await route.fulfill({ response: res, json: out });
    },
  );
}

/**
 * Swallow the given setTimeout delays so time-boxed UI holds for the capture:
 * 5000 = toast auto-dismiss (ToastProvider), 3000 = useConfirm's armed window.
 */
async function pinTimers(page: Page, delays: number[]): Promise<void> {
  await page.addInitScript((ds) => {
    const orig = window.setTimeout.bind(window);
    window.setTimeout = ((fn: TimerHandler, ms?: number, ...args: unknown[]) =>
      ds.includes(Number(ms)) ? 0 : orig(fn, ms, ...args)) as typeof window.setTimeout;
  }, delays);
}
const pinToasts = (page: Page) => pinTimers(page, [5000]);
const pinArmed = (page: Page) => pinTimers(page, [3000]);

/**
 * Freeze hover/focus/drag state: after this, pointer/mouse/focus events stop
 * at window capture, so the harness's mouse.move(0,0) + blur() cannot reach
 * React (or the graph's pointer handlers) and tear the state down.
 */
async function freeze(page: Page): Promise<void> {
  await page.evaluate(() => {
    const stop = (e: Event) => e.stopImmediatePropagation();
    for (const t of [
      "pointerover", "pointerenter", "pointerout", "pointerleave", "pointermove", "pointerup", "pointercancel",
      "mouseover", "mouseenter", "mouseout", "mouseleave", "mousemove", "mouseup",
      "focusout", "blur", "lostpointercapture",
    ]) {
      window.addEventListener(t, stop, true);
    }
  });
}

/** One SSE frame in the chat-stream wire format (lib/api.ts consumeChatStream). */
function sse(type: string, data: unknown = null, step: string = type, message = ""): string {
  return `event: ${type}\ndata: ${JSON.stringify({ type, step, message, data })}\n\n`;
}

/** Token frames for `text`, in small chunks. */
function tokens(t: string): string[] {
  const out: string[] = [];
  for (let i = 0; i < t.length; i += 24) out.push(sse("token", { delta: t.slice(i, i + 24) }, "reply"));
  return out;
}

/**
 * Serve POSTs to a path ending in `suffix` from an in-page fake SSE stream:
 * `frames` are enqueued at once; `close: false` leaves the stream open forever
 * (holds a mid-stream state). Honors the request's AbortSignal so Stop works.
 * Never reaches the backend, so nothing persists.
 */
async function fakeStream(
  page: Page,
  suffix: string,
  frames: string[],
  close: boolean,
): Promise<void> {
  await page.addInitScript(
    ({ suffix, frames, close }) => {
      const orig = window.fetch.bind(window);
      window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
        const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        const path = new URL(raw, window.location.href).pathname;
        if (!path.endsWith(suffix)) return orig(input, init);
        const enc = new TextEncoder();
        const signal = init?.signal;
        const body = new ReadableStream<Uint8Array>({
          start(c) {
            for (const f of frames) c.enqueue(enc.encode(f));
            if (close) c.close();
            signal?.addEventListener("abort", () => {
              try {
                c.error(new DOMException("The operation was aborted.", "AbortError"));
              } catch {
                /* already closed */
              }
            });
          },
        });
        return Promise.resolve(
          new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }),
        );
      };
    },
    { suffix, frames, close },
  );
}

/** Streamed tutor turn: tokens + `done`, closed. */
function finishedTurn(reply: string): string[] {
  return [...tokens(reply), sse("done", { reply, graph_update: {}, mastery_changes: [] }, "done")];
}

/** Resume the seeded Recursion session (no LLM call). */
async function openRecursion(page: Page): Promise<void> {
  await page.goto("/learn");
  await page.getByTestId(`tutor-session-resume-${SESSION_RECURSION}`).click();
  await visible(page, "tutor-input");
  await expect(page.getByTestId("tutor-messages")).toContainText(/recursion/i, { timeout: 30_000 });
}

async function sendTurn(page: Page, msg: string): Promise<void> {
  await page.getByTestId("tutor-input").fill(msg);
  await page.getByTestId("tutor-send").click();
}

/** Wait for the rail's focus card (graph + description loaded). */
async function railReady(page: Page): Promise<void> {
  await visible(page, "tutor-focus-concept-description");
}

/** Activate a graph node through its a11y twin (SVG positions are layout-dependent). */
async function activateNode(page: Page, nodeId: string): Promise<void> {
  await page
    .getByTestId("graph-container")
    .first()
    .locator(`[data-testid="graph-node-item"][data-node-id="${nodeId}"] [data-testid="graph-node-activate"]`)
    .dispatchEvent("click");
}

/** The 2D SVG circle of one node. */
function nodeCircle(page: Page, nodeId: string) {
  return page
    .locator(`[data-testid="graph-node"][data-node-id="${nodeId}"]`)
    .first()
    .getByTestId("graph-node-circle")
    .first();
}

async function waitGraph(page: Page): Promise<void> {
  await expect(
    page.getByTestId("graph-container").first().getByTestId("graph-node").first(),
  ).toBeVisible({ timeout: 30_000 });
}

async function toast(page: Page, t: string | RegExp): Promise<void> {
  await expect(page.getByRole("status").filter({ hasText: t }).first()).toBeVisible({ timeout: 15_000 });
}

async function openDashboard(page: Page): Promise<void> {
  await page.goto("/dashboard");
  await visible(page, "dashboard-review-due");
}

async function openCoursesKey(page: Page): Promise<void> {
  await page.getByTestId("dashboard-courses-key-toggle").click();
  await visible(page, "dashboard-courses-manage");
}

async function openManageModal(page: Page): Promise<void> {
  await openDashboard(page);
  await openCoursesKey(page);
  await page.getByTestId("dashboard-courses-manage").click();
  await text(page, "Personal learning");
}

async function openTree(page: Page, path = "/tree"): Promise<void> {
  await page.goto(path);
  await waitGraph(page);
}

async function treeCourse(page: Page, courseId = COURSE_CS101): Promise<void> {
  await openTree(page);
  await page.getByTestId(`graph-course-filter-${courseId}`).click();
  await visible(page, "topic-checklist-toggle");
}

async function openChecklist(page: Page): Promise<void> {
  await treeCourse(page);
  await page.getByTestId("topic-checklist-toggle").click();
}

/** Pick a course in /learn's "Course (optional)" CustomSelect. */
async function pickLearnCourse(page: Page, code: string): Promise<void> {
  await page.getByRole("button", { name: /No course/ }).click();
  await page.getByRole("option", { name: new RegExp(`^${code}`) }).click();
}

async function openLearnEntry(page: Page): Promise<void> {
  await page.goto("/learn");
  await visible(page, "tutor-topic-picker");
}

/** Start a session on a custom topic over a fake (closed) start stream. */
async function startFakeSession(page: Page, topic: string, courseCode?: string): Promise<void> {
  await fakeStream(
    page,
    "/api/learn/start-session/stream",
    [
      ...tokens(`Let's dig into ${topic}. What do you already know about it?`),
      sse("done", {
        reply: `Let's dig into ${topic}. What do you already know about it?`,
        session_id: "figma-fake-session",
        graph_update: {},
        mastery_changes: [],
        graph_state: null,
      }, "done"),
    ],
    true,
  );
  await openLearnEntry(page);
  if (courseCode) await pickLearnCourse(page, courseCode);
  await page.getByTestId("tutor-topic-picker").click();
  await page.getByTestId("tutor-topic-search").fill(topic);
  await page.keyboard.press("Enter");
  await page.getByTestId("tutor-start").click();
  await visible(page, "tutor-input");
  await expect(page.getByTestId("tutor-messages")).toContainText("What do you already know", { timeout: 30_000 });
}

/** Stub WebGL. `mode: "all"` = no WebGL at all; `"renderer"` = the capability
 *  probe (getContext("webgl2") with no attributes) succeeds but the renderer's
 *  attributed getContext returns null → three throws → graph crash boundary. */
async function stubWebgl(page: Page, mode: "all" | "renderer"): Promise<void> {
  await page.addInitScript((m) => {
    const orig = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement,
      kind: string,
      ...rest: unknown[]
    ) {
      const gl = kind === "webgl" || kind === "webgl2" || kind === "experimental-webgl";
      if (gl && (m === "all" || (rest.length > 0 && rest[0] !== undefined))) return null;
      return (orig as (this: HTMLCanvasElement, k: string, ...a: unknown[]) => unknown).call(this, kind, ...rest);
    } as typeof HTMLCanvasElement.prototype.getContext;
    window.localStorage.setItem("sapling.kg.mode", "3d");
  }, mode);
}

// ── Fixtures ───────────────────────────────────────────────────────────────

const FENCE = "```";

const STREAM_TEXT =
  "Good question. Think of each recursive call as a promise to finish later: " +
  "factorial(3) cannot answer until factorial(2) does, and factorial(2) waits on " +
  "factorial(1). The base case is the first call that can answer immediately, and " +
  "once it does, every waiting frame on the stack resolves in reverse order. So what " +
  "do you think happens if the base case can never be reached?";

const MARKDOWN_RICH = [
  "## Recursion, step by step",
  "",
  "Every recursive function has **two parts**:",
  "",
  "1. A *base case* that stops the descent",
  "2. A recursive step that makes the problem smaller",
  "",
  "| n | factorial(n) |",
  "|---|---|",
  "| 0 | 1 |",
  "| 3 | 6 |",
  "| 5 | 120 |",
  "",
  `${FENCE}python`,
  "def factorial(n):",
  "    if n == 0:",
  "        return 1",
  "    return n * factorial(n - 1)",
  FENCE,
  "",
  "The running time satisfies $T(n) = T(n-1) + O(1)$, which solves to",
  "",
  "$$",
  "T(n) = O(n)",
  "$$",
  "",
  "> Tip: trace `factorial(3)` on paper before you run it.",
].join("\n");

const MARKDOWN_MERMAID = [
  "Here is the call tree for `factorial(3)`:",
  "",
  `${FENCE}mermaid`,
  "graph TD",
  '  A["factorial(3)"] --> B["factorial(2)"]',
  '  B --> C["factorial(1)"]',
  '  C --> D["factorial(0) = 1"]',
  FENCE,
  "",
  "Each arrow is one frame waiting on the next.",
].join("\n");

const MARKDOWN_PLOT = [
  "Compare linear and exponential growth:",
  "",
  `${FENCE}plot`,
  "title: n vs 2^n",
  "plot: x; color=#4e873c",
  "plot: 2^x; color=#b4562c",
  "x: [0, 6]",
  "y: [0, 40]",
  FENCE,
  "",
  "Naive recursive fibonacci sits on the steep curve.",
].join("\n");

function assignment(id: string, title: string, due: string, type: string, course: string) {
  return { id, user_id: "rich-user-active", title, due_date: due, assignment_type: type, course_name: course };
}

// Frozen clock: 2026-03-11T12:00:00Z.
const CHIP_ASSIGNMENTS = [
  assignment("fig-a1", "Problem Set 4", "2026-03-11T10:00:00Z", "homework", "Introduction to Computer Science"), // OVERDUE
  assignment("fig-a2", "Reading Quiz 3", "2026-03-11T20:00:00Z", "quiz", "Cell Biology"), // 8H
  assignment("fig-a3", "Lab Report 2", "2026-03-13T09:00:00Z", "project", "Linear Algebra"), // 2D warn
  assignment("fig-a4", "Midterm 1", "2026-03-17T14:00:00Z", "exam", "Introduction to Computer Science"), // 7D info
];

type Topic = Record<string, unknown>;

function topic(over: Topic): Topic {
  return {
    description: "",
    importance: 0.5,
    parent_id: null,
    prerequisite_ids: [],
    prerequisite_gaps: [],
    checked: false,
    mastery_score: null,
    last_studied_at: null,
    review_reasons: [],
    priority: "normal",
    assessments: [],
    sources: [],
    node_id: null,
    ...over,
  };
}

const MIDTERM = { id: "fig-midterm", title: "Midterm 1", due_date: "2026-03-17", assignment_type: "exam" };

const CHECKLIST_TOPICS: Topic[] = [
  topic({
    id: "fig-t-variables",
    name: "Variables and Types",
    description: "Naming values, primitive types, and how Python binds names to objects.",
    status: "mastered",
    checked: true,
    mastery_score: 0.92,
    sources: [{ id: "s1", label: "Lecture 2 — Values and Types" }],
    node_id: "rich-node-cs-variables",
  }),
  topic({
    id: "fig-t-controlflow",
    name: "Control Flow",
    description: "Conditionals and loops: choosing and repeating work.",
    status: "in_progress",
    checked: true,
    mastery_score: 0.6,
    sources: [{ id: "s2", label: "Lecture 4 — Branching" }],
    node_id: "rich-node-cs-controlflow",
  }),
  topic({
    id: "fig-t-recursion",
    name: "Recursion",
    description: "Functions that call themselves on a smaller version of the same problem.",
    importance: 0.9,
    status: "needs_review",
    checked: true,
    mastery_score: 0.25,
    review_reasons: ["Mastery is below 45%", "Last quiz scored 6/10"],
    prerequisite_gaps: ["Control Flow"],
    priority: "high",
    assessments: [MIDTERM],
    sources: [{ id: "s3", label: "Lecture 6 — Recursion" }, { id: "s4", label: "Problem Set 4" }],
    node_id: NODE_RECURSION,
  }),
  topic({
    id: "fig-t-basecase",
    name: "Base cases",
    description: "The stopping condition every recursive function needs.",
    parent_id: "fig-t-recursion",
    status: "not_started",
    assessments: [MIDTERM],
    sources: [{ id: "s3", label: "Lecture 6 — Recursion" }],
  }),
  topic({
    id: "fig-t-pointers",
    name: "Pointers and Memory",
    description: "References, aliasing, and how values live in memory.",
    status: "not_started",
    mastery_score: 0.05,
    sources: [{ id: "s5", label: "Course catalog" }],
    node_id: "rich-node-cs-pointers",
  }),
];

function checklist(over: Record<string, unknown> = {}) {
  return {
    course_id: COURSE_CS101,
    semester: "Spring 2026",
    generated_at: "2026-03-10T15:00:00Z",
    needs_refresh: false,
    topics: CHECKLIST_TOPICS,
    assessments: [MIDTERM],
    warnings: [],
    review_after_days: 7,
    ...over,
  };
}

function attempt(id: string, score: number, total: number, delta: number, completed: string) {
  return {
    quiz_id: id,
    status: "completed",
    concept_node_id: NODE_RECURSION,
    concept_name: "Recursion",
    course_id: COURSE_CS101,
    score,
    total,
    difficulty: "medium",
    mastery_before: 0.2,
    mastery_after: 0.2 + delta,
    mastery_delta: delta,
    created_at: completed,
    completed_at: completed,
  };
}

const SUMMARY = {
  concepts_covered: ["Recursion", "Base Case", "Call Stack"],
  mastery_changes: [
    { concept: "Recursion", before: 0.25, after: 0.41 },
    { concept: "Call Stack", before: 0.3, after: 0.22 },
  ],
  new_connections: [],
  time_spent_minutes: 14,
  recommended_next: ["Tail Recursion", "Algorithms"],
};

// ── Recipes ────────────────────────────────────────────────────────────────

export const RECIPES_CORE: RecipeBook = {
  // ── Shared KnowledgeGraph ───────────────────────────────────────────────
  "graph/2d-populated": {
    run: async (page) => {
      await openTree(page);
      await visible(page, "graph-zoom-in");
      await expect(page.getByTestId("graph-mode-toggle")).toHaveText("2D");
    },
  },

  "graph/2d-empty": {
    run: async (page) => {
      await mockJson(page, GRAPH, EMPTY_GRAPH);
      await openDashboard(page);
      await visible(page, "graph-container");
      await expect(page.getByTestId("graph-node")).toHaveCount(0);
    },
  },

  "graph/node-hover-tooltip": {
    run: async (page) => {
      await openTree(page);
      await page.waitForTimeout(1_500); // layout settles before aiming
      await nodeCircle(page, NODE_RECURSION).hover({ force: true });
      await expect(page.getByText("Mastery", { exact: true })).toBeVisible({ timeout: 10_000 });
      await freeze(page);
    },
  },

  "graph/highlight-pulse": {
    run: async (page) => {
      await page.goto("/dashboard?suggest=Recursion");
      await text(page, "Try this next:");
      await page.getByRole("button", { name: "Fullscreen graph" }).click();
      await text(page, "Press Esc to exit");
      await waitGraph(page);
      await expect(
        page.locator(`[data-testid="graph-node"][data-node-id="${NODE_RECURSION}"] animate`).first(),
      ).toBeAttached();
    },
  },

  "graph/node-dragging": {
    run: async (page) => {
      await openTree(page);
      await page.waitForTimeout(1_500);
      const box = await nodeCircle(page, NODE_RECURSION).boundingBox();
      if (!box) throw new Error("recursion node has no box");
      const x = box.x + box.width / 2;
      const y = box.y + box.height / 2;
      await page.mouse.move(x, y);
      await page.mouse.down();
      await page.mouse.move(x + 40, y + 20, { steps: 4 });
      await page.mouse.move(x + 90, y + 50, { steps: 4 });
      await freeze(page);
      // Drag hides the hover card.
      await expect(page.getByText("Mastery", { exact: true })).toHaveCount(0);
    },
  },

  "graph/3d": {
    run: async (page) => {
      await storage(page, { "sapling.kg.mode": "3d" });
      await page.goto("/tree");
      await expect(page.getByTestId("graph-mode-toggle")).toHaveText("3D", { timeout: 30_000 });
      await expect(page.getByTestId("graph-container").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(2_000);
    },
  },

  "graph/no-webgl": {
    run: async (page) => {
      await stubWebgl(page, "all");
      await openTree(page);
      await expect(page.getByTestId("graph-mode-toggle")).toHaveAttribute("aria-disabled", "true");
      await expect(page.getByTestId("graph-mode-toggle")).toHaveAttribute("title", "3D requires WebGL");
    },
  },

  "graph/crash-fallback": {
    run: async (page) => {
      await stubWebgl(page, "renderer");
      await page.goto("/tree");
      await visible(page, "graph-crash-fallback");
      await visible(page, "graph-crash-retry");
    },
  },

  // ── /dashboard ──────────────────────────────────────────────────────────
  "dashboard/loading": {
    run: async (page) => {
      await hold(page, GRAPH);
      await page.goto("/dashboard");
      await expect(page.locator(".skeleton").first()).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("dashboard-review-due")).toHaveCount(0);
    },
  },

  "dashboard/error": {
    run: async (page) => {
      await mockError(page, GRAPH, 500, "Internal Server Error", "GET");
      await page.goto("/dashboard");
      await text(page, "Couldn't load dashboard");
      await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
    },
  },

  "dashboard/populated-sidebar": {
    run: async (page) => {
      await page.goto("/dashboard");
      await visible(page, "dashboard-review-due");
      await expect(page.getByTestId("graph-node").first()).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(3_000); // typewriter greeting + quote settle
    },
  },

  "dashboard/greeting-typing": {
    run: async (page) => {
      // Let the 55ms typewriter tick 9 times, then stall it mid-word.
      await page.addInitScript(() => {
        const orig = window.setInterval.bind(window);
        window.setInterval = ((fn: TimerHandler, ms?: number, ...args: unknown[]) => {
          if (ms !== 55 || typeof fn !== "function") return orig(fn, ms, ...args);
          let n = 0;
          return orig((...a: unknown[]) => {
            n += 1;
            if (n <= 9) (fn as (...x: unknown[]) => void)(...a);
          }, ms, ...args);
        }) as typeof window.setInterval;
      });
      await openDashboard(page);
      await page.waitForTimeout(1_500);
      await expect(page.locator("h1").first()).not.toContainText(",");
      await expect(page.locator("p.body-serif[aria-hidden='true']").first()).toBeAttached();
    },
  },

  "dashboard/greeting-no-name": {
    run: async (page) => {
      await storage(page, {
        sapling_user: JSON.stringify({ id: "rich-user-active", name: "", avatar: "" }),
      });
      await patchJson(page, /^\/api\/auth\/me/, (me) => {
        me.name = "";
      });
      await openDashboard(page);
      await expect(page.locator("h1").first()).toContainText("Welcome back", { timeout: 15_000 });
      await page.waitForTimeout(1_500);
    },
  },

  "dashboard/review-due-count": {
    run: async (page) => {
      await openDashboard(page);
      await expect(page.getByTestId("dashboard-review-due")).toContainText("Review what's due ·");
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/review-quiz": {
    run: async (page) => {
      await patchJson(page, GRAPH, (g) => {
        for (const n of g.nodes) if (!n.is_subject_root) n.mastery_tier = "mastered";
      });
      await openDashboard(page);
      await expect(page.getByTestId("dashboard-review-due")).toContainText("Quiz");
      await expect(page.getByTestId("dashboard-review-due")).not.toContainText("Review");
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/streak-zero": {
    run: async (page) => {
      await patchJson(page, GRAPH, (g) => {
        g.stats = { ...g.stats, streak: 0 };
      });
      await openDashboard(page);
      await text(page, "Personal best: 0");
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/streak-active": {
    run: async (page) => {
      await openDashboard(page);
      await expect(page.getByText(/^Personal best: [1-9]\d*$/).first()).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/mastered-empty": {
    run: async (page) => {
      await patchJson(page, GRAPH, (g) => {
        g.stats = { ...g.stats, mastered: 0, total_nodes: 0 };
      });
      await openDashboard(page);
      await text(page, "no concepts yet");
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/sessions-empty": {
    run: async (page) => {
      await mockJson(page, SESSIONS_LIST, { sessions: [] });
      await openDashboard(page);
      await text(page, "No recent sessions — start learning to fill this in.");
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/upcoming-empty": {
    run: async (page) => {
      await mockJson(page, UPCOMING, { assignments: [] });
      await openDashboard(page);
      await text(page, "No upcoming assignments.");
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/upcoming-chips": {
    run: async (page) => {
      await mockJson(page, UPCOMING, { assignments: CHIP_ASSIGNMENTS });
      await openDashboard(page);
      await text(page, "OVERDUE");
      await expect(page.locator(".chip--warn").first()).toHaveText("2D");
      await expect(page.locator(".chip--info").first()).toHaveText("7D");
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/empty-new-student": {
    run: async (page) => {
      await mockJson(page, GRAPH, EMPTY_GRAPH);
      await mockJson(page, COURSES, { courses: [] }, { method: "GET" });
      await mockJson(page, RECS, { recommendations: [] });
      await mockJson(page, SESSIONS_LIST, { sessions: [] });
      await mockJson(page, UPCOMING, { assignments: [] });
      await openDashboard(page);
      await text(page, "No recent sessions — start learning to fill this in.");
      await text(page, "No upcoming assignments.");
      await text(page, "no concepts yet");
      await expect(page.getByTestId("dashboard-courses-key-toggle")).toHaveCount(0);
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/courses-key-collapsed": {
    run: async (page) => {
      await openDashboard(page);
      await expect(page.getByTestId("dashboard-courses-key-toggle")).toHaveAttribute("aria-label", "Expand courses key");
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/courses-key-expanded": {
    run: async (page) => {
      await openDashboard(page);
      await openCoursesKey(page);
      await expect(page.getByTestId("dashboard-course-code").first()).toBeVisible();
      await page.waitForTimeout(1_500);
    },
  },

  "dashboard/courses-key-empty-term": {
    run: async (page) => {
      // A stored term none of the courses belong to; the graph/recs fetches
      // are served unscoped so the backend never sees the made-up term.
      await storage(page, { sapling_active_semester: "Summer 2027" });
      for (const p of [GRAPH, RECS]) {
        await page.route(
          (url) => p.test(url.pathname + url.search),
          async (route) => {
            const u = new URL(route.request().url());
            u.searchParams.delete("semester");
            await route.fulfill({ response: await route.fetch({ url: u.toString() }) });
          },
        );
      }
      await openDashboard(page);
      await page.getByTestId("dashboard-courses-key-toggle").click();
      await text(page, "Nothing enrolled this semester.");
    },
  },

  "dashboard/courses-key-hidden": {
    run: async (page) => {
      await mockJson(page, COURSES, { courses: [] }, { method: "GET" });
      await openDashboard(page);
      await waitGraph(page);
      await expect(page.getByTestId("dashboard-courses-key-toggle")).toHaveCount(0);
      await page.waitForTimeout(1_500);
    },
  },

  "dashboard/suggest-banner": {
    run: async (page) => {
      await page.goto("/dashboard?suggest=Recursion");
      await text(page, "Try this next:");
      await expect(page.getByRole("button", { name: "Start quiz" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Dismiss" })).toBeVisible();
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/fullscreen-graph": {
    run: async (page) => {
      await openDashboard(page);
      await page.getByRole("button", { name: "Fullscreen graph" }).click();
      await text(page, "Knowledge graph — fullscreen");
      await text(page, "Press Esc to exit");
      await waitGraph(page);
    },
  },

  "dashboard/manage-courses-modal": {
    run: async (page) => {
      await openManageModal(page);
      await expect(page.getByRole("button", { name: "All semesters" })).toBeVisible();
      await expect(page.getByLabel("Search courses")).toBeVisible();
      await page.waitForTimeout(1_000); // catalog search (200ms debounce) lands
    },
  },

  "dashboard/manage-courses-modal-empty": {
    run: async (page) => {
      // Sidebar layout hides the cog with 0 courses; the topnav panel keeps
      // its "Courses & Semesters" button.
      await storage(page, { sapling_layout: "topnav" });
      await mockJson(page, COURSES, { courses: [] }, { method: "GET" });
      await mockJson(page, ONBOARDING_SEARCH, { courses: [] });
      await openDashboard(page);
      await page.getByRole("button", { name: "Courses & Semesters" }).click();
      await text(page, "No semesters yet — add a course below.");
      await text(page, "No courses in this semester yet.");
      await text(page, "No matches.");
    },
  },

  "dashboard/manage-courses-searching": {
    run: async (page) => {
      await hold(page, ONBOARDING_SEARCH);
      await openManageModal(page);
      await page.getByLabel("Search courses").fill("CS 2");
      await text(page, "Searching…");
    },
  },

  "dashboard/toast-color-updated": {
    run: async (page) => {
      await pinToasts(page);
      await mockJson(page, COURSE_COLOR, { updated: true }, { method: "PATCH" });
      await openManageModal(page);
      const hex = page.locator("input.mono").first();
      await hex.fill("#3e6f8a");
      await hex.press("Enter");
      await toast(page, "Color updated");
    },
  },

  "dashboard/toast-course-removed": {
    run: async (page) => {
      await pinToasts(page);
      await mockJson(page, COURSE_ITEM, { deleted: true }, { method: "DELETE" });
      await openManageModal(page);
      const remove = page.getByRole("button", { name: "Remove course" }).first();
      await remove.click();
      await page.getByRole("button", { name: "Click again" }).first().click();
      await toast(page, /^Removed /);
    },
  },

  "dashboard/toast-failed": {
    run: async (page) => {
      await pinToasts(page);
      await mockError(page, COURSE_COLOR, 500, "Internal Server Error", "PATCH");
      await openManageModal(page);
      const hex = page.locator("input.mono").first();
      await hex.fill("#b4562c");
      await hex.press("Enter");
      await toast(page, /^Failed:/);
    },
  },

  "dashboard/topnav-populated": {
    run: async (page) => {
      await storage(page, { sapling_layout: "topnav" });
      await openDashboard(page);
      await text(page, "This week");
      await text(page, "Learn next");
      await waitGraph(page);
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/topnav-streak-strip": {
    run: async (page) => {
      // Frozen today = Wed 2026-03-11: Mon + Wed studied, Tue missed, Thu+ future.
      await storage(page, { sapling_layout: "topnav" });
      await patchJson(page, GRAPH, (g) => {
        const concepts = g.nodes.filter((n: { is_subject_root?: boolean }) => !n.is_subject_root);
        concepts.forEach((n: { last_studied_at: string | null }, i: number) => {
          n.last_studied_at = i % 2 === 0 ? "2026-03-09T15:00:00Z" : "2026-03-11T09:00:00Z";
        });
        g.stats = { ...g.stats, streak: 12 };
      });
      await openDashboard(page);
      await text(page, "This week");
      await text(page, /12-day/);
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/topnav-learn-next-empty": {
    run: async (page) => {
      await storage(page, { sapling_layout: "topnav" });
      await mockJson(page, RECS, { recommendations: [] });
      await openDashboard(page);
      await text(page, "Nothing suggested yet — start a session.");
      await page.waitForTimeout(2_000);
    },
  },

  "dashboard/topnav-courses-empty": {
    run: async (page) => {
      await storage(page, { sapling_layout: "topnav" });
      await mockJson(page, COURSES, { courses: [] }, { method: "GET" });
      await openDashboard(page);
      await text(page, "No enrolled courses yet.");
      await page.waitForTimeout(2_000);
    },
  },

  // ── /learn ──────────────────────────────────────────────────────────────
  "learn/disclaimer-modal": {
    run: async (page) => {
      // Runs after the harness's ack init script → the modal shows.
      await page.addInitScript(() => window.localStorage.removeItem("sapling_disclaimer_ack"));
      await page.goto("/learn");
      await expect(page.getByRole("dialog", { name: "Sapling uses AI" })).toBeVisible({ timeout: 30_000 });
      await expect(page.getByRole("button", { name: "Got it" })).toBeVisible();
    },
  },

  "learn/entry-populated": {
    run: async (page) => {
      await openLearnEntry(page);
      await visible(page, `tutor-session-resume-${SESSION_RECURSION}`);
      await expect(page.getByTestId("tutor-start")).toBeDisabled();
    },
  },

  "learn/entry-empty": {
    run: async (page) => {
      await mockJson(page, SESSIONS_LIST, { sessions: [] });
      await mockJson(page, COURSES, { courses: [] }, { method: "GET" });
      await mockJson(page, GRAPH, EMPTY_GRAPH);
      await openLearnEntry(page);
      await text(page, "No recent sessions yet.");
      await expect(page.getByTestId("tutor-start")).toBeDisabled();
    },
  },

  "learn/entry-topic-prefilled": {
    run: async (page) => {
      await page.goto(`/learn?topic=Recursion&mode=expository&course=${COURSE_CS101}`);
      await expect(page.getByTestId("tutor-topic-picker")).toContainText("Recursion", { timeout: 30_000 });
      await expect(page.getByRole("button", { name: /^CS101/ })).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("tutor-start")).toBeEnabled();
    },
  },

  "learn/entry-course-select-open": {
    run: async (page) => {
      await openLearnEntry(page);
      await visible(page, `tutor-session-resume-${SESSION_RECURSION}`); // courses loaded
      await page.getByRole("button", { name: /No course/ }).click();
      await expect(page.getByRole("listbox")).toBeVisible();
      await expect(page.getByRole("option", { name: /^CS101/ })).toBeVisible();
    },
  },

  "learn/topic-picker-open": {
    run: async (page) => {
      await openLearnEntry(page);
      await visible(page, `tutor-session-resume-${SESSION_RECURSION}`);
      await page.getByTestId("tutor-topic-picker").click();
      await visible(page, "tutor-topic-search");
      await text(page, "Tutor scans your graph and chooses the next concept.");
      await expect(page.getByRole("button", { name: /^Recursion/ }).first()).toBeVisible();
    },
  },

  "learn/topic-picker-custom": {
    run: async (page) => {
      await openLearnEntry(page);
      await page.getByTestId("tutor-topic-picker").click();
      await page.getByTestId("tutor-topic-search").fill("Dynamic programming on trees");
      await text(page, "Use custom topic:");
    },
  },

  "learn/topic-picker-empty-course": {
    run: async (page) => {
      // ENG150 is enrolled but has no graph nodes in the seed.
      await openLearnEntry(page);
      await visible(page, `tutor-session-resume-${SESSION_RECURSION}`);
      await pickLearnCourse(page, "ENG150");
      await page.getByTestId("tutor-topic-picker").click();
      await text(page, "No concepts in this course yet — upload a syllabus or scan to populate the graph.");
    },
  },

  "learn/topic-picker-empty-graph": {
    run: async (page) => {
      await mockJson(page, GRAPH, EMPTY_GRAPH);
      await openLearnEntry(page);
      await page.getByTestId("tutor-topic-picker").click();
      await text(page, "No concepts in your graph yet.");
    },
  },

  "learn/topic-general-selected": {
    run: async (page) => {
      await openLearnEntry(page);
      await visible(page, `tutor-session-resume-${SESSION_RECURSION}`);
      await pickLearnCourse(page, "CS101");
      await page.getByTestId("tutor-topic-picker").click();
      await page.getByRole("button", { name: /^General — pick what's next in CS101/ }).click();
      await expect(page.getByTestId("tutor-topic-picker")).toContainText("General — pick what's next in CS101");
    },
  },

  "learn/shared-ctx-off": {
    run: async (page) => {
      await openLearnEntry(page);
      const sw = page.getByRole("switch", { name: /Class intel/ });
      if ((await sw.getAttribute("aria-checked")) === "true") await sw.click();
      await expect(sw).toHaveAttribute("aria-checked", "false");
    },
  },

  "learn/shared-ctx-tooltip": {
    run: async (page) => {
      await openLearnEntry(page);
      await page.getByRole("switch", { name: /Class intel/ }).hover();
      await expect(page.getByRole("tooltip").filter({ hasText: "Shared course context" })).toBeVisible();
      await freeze(page);
    },
  },

  "learn/ai-chip-tooltip": {
    run: async (page) => {
      await openLearnEntry(page);
      await page.getByRole("button", { name: "Review AI guidelines" }).hover();
      await expect(page.getByRole("tooltip").filter({ hasText: "AI powered learning" })).toBeVisible();
      await freeze(page);
    },
  },

  "learn/ai-chip-modal": {
    run: async (page) => {
      await openLearnEntry(page);
      await page.getByRole("button", { name: "Review AI guidelines" }).click();
      await expect(page.getByRole("dialog", { name: "Sapling uses AI" })).toBeVisible();
    },
  },

  "learn/session-row-renaming": {
    run: async (page) => {
      await openLearnEntry(page);
      await visible(page, `tutor-session-resume-${SESSION_RECURSION}`);
      await page.getByRole("button", { name: "Rename session" }).first().click();
      await expect(page.getByLabel("Session name")).toBeFocused();
      await freeze(page); // the harness's blur() would otherwise commit + close it
    },
  },

  "learn/session-row-delete-armed": {
    run: async (page) => {
      await pinArmed(page);
      await openLearnEntry(page);
      await visible(page, `tutor-session-resume-${SESSION_RECURSION}`);
      await page.getByRole("button", { name: "Delete session" }).first().click();
      await expect(page.getByRole("button", { name: "Confirm delete" })).toBeVisible();
    },
  },

  "learn/toast-session-deleted": {
    run: async (page) => {
      await pinToasts(page);
      await mockJson(page, SESSION_ITEM, { deleted: true }, { method: "DELETE" });
      await openLearnEntry(page);
      await visible(page, `tutor-session-resume-${SESSION_RECURSION}`);
      await page.getByRole("button", { name: "Delete session" }).last().click();
      await page.getByRole("button", { name: "Confirm delete" }).click();
      await toast(page, "Session deleted.");
    },
  },

  "learn/toast-session-delete-failed": {
    run: async (page) => {
      await pinToasts(page);
      await mockError(page, SESSION_ITEM, 500, "Couldn't delete this session.", "DELETE");
      await openLearnEntry(page);
      await visible(page, `tutor-session-resume-${SESSION_RECURSION}`);
      await page.getByRole("button", { name: "Delete session" }).first().click();
      await page.getByRole("button", { name: "Confirm delete" }).click();
      await expect(page.getByRole("status").first()).toBeVisible({ timeout: 15_000 });
      await visible(page, `tutor-session-resume-${SESSION_RECURSION}`);
    },
  },

  "learn/toast-session-rename-failed": {
    run: async (page) => {
      await pinToasts(page);
      await mockError(page, SESSION_ITEM, 500, "Couldn't rename this session.", "PATCH");
      await openLearnEntry(page);
      await visible(page, `tutor-session-resume-${SESSION_RECURSION}`);
      await page.getByRole("button", { name: "Rename session" }).first().click();
      const input = page.getByLabel("Session name");
      await input.fill("Recursion deep dive");
      await input.press("Enter");
      await expect(page.getByRole("status").first()).toBeVisible({ timeout: 15_000 });
    },
  },

  "learn/resume-loading": {
    run: async (page) => {
      await hold(page, RESUME);
      await page.goto(`/learn?resume=${SESSION_RECURSION}`);
      await visible(page, "tutor-resume-loading");
    },
  },

  "learn/resume-failed": {
    run: async (page) => {
      await pinToasts(page);
      await mockError(page, RESUME, 404, "Session not found");
      await page.goto(`/learn?resume=${SESSION_RECURSION}`);
      await toast(page, /Session not found|Resume failed/);
      await visible(page, "tutor-topic-picker");
    },
  },

  "learn/starting-thinking": {
    run: async (page) => {
      await hold(page, "/api/learn/start-session/stream");
      await openLearnEntry(page);
      await visible(page, `tutor-session-resume-${SESSION_RECURSION}`);
      await page.getByTestId("tutor-topic-picker").click();
      await page.getByTestId("tutor-topic-search").fill("Recursion");
      await page.keyboard.press("Enter");
      await page.getByTestId("tutor-start").click();
      await visible(page, "tutor-stop");
      await expect(page.getByTestId("tutor-messages")).toContainText("Thinking…");
      await expect(page.getByTestId("tutor-input")).toBeDisabled();
    },
  },

  "learn/streaming-status": {
    run: async (page) => {
      await fakeStream(page, "/api/learn/chat/stream", [sse("progress", null, "search_course_materials")], false);
      await openRecursion(page);
      await sendTurn(page, "Can you show me where recursion shows up in my lecture notes?");
      await expect(page.getByTestId("tutor-messages")).toContainText("Searching your course materials…");
      await visible(page, "tutor-stop");
    },
  },

  "learn/streaming-text": {
    run: async (page) => {
      await fakeStream(page, "/api/learn/chat/stream", tokens(STREAM_TEXT), false);
      await openRecursion(page);
      await sendTurn(page, "Why does the call stack unwind in reverse order?");
      await expect(page.getByTestId("tutor-messages")).toContainText("base case can never be reached", { timeout: 15_000 });
      await visible(page, "tutor-stop");
      await expect(page.getByTestId("tutor-input")).toBeDisabled();
    },
  },

  "learn/greeting-failed": {
    run: async (page) => {
      await pinToasts(page);
      // Both the stream and the JSON fallback rung fail.
      await mockError(page, "/api/learn/start-session", 500, "The tutor is unavailable right now.");
      await openLearnEntry(page);
      await page.getByTestId("tutor-topic-picker").click();
      await page.getByTestId("tutor-topic-search").fill("Recursion");
      await page.keyboard.press("Enter");
      await page.getByTestId("tutor-start").click();
      await expect(page.getByRole("status").first()).toBeVisible({ timeout: 15_000 });
      await expect(page.getByTestId("tutor-topic-picker")).toContainText("Recursion");
    },
  },

  "learn/active-idle": {
    run: async (page) => {
      await page.goto("/learn");
      await page.getByRole("button", { name: /Recursion socratic/ }).click();
      await visible(page, "tutor-input");
    },
  },

  "learn/active-finished-reply": {
    run: async (page) => {
      await fakeStream(page, "/api/learn/chat/stream", finishedTurn(STREAM_TEXT), true);
      await openRecursion(page);
      await sendTurn(page, "Why does the call stack unwind in reverse order?");
      await expect(page.getByTestId("tutor-messages")).toContainText("base case can never be reached", { timeout: 15_000 });
      await expect(page.getByTestId("tutor-stop")).toHaveCount(0, { timeout: 15_000 });
      await expect(page.getByTestId("tutor-input")).toBeEnabled();
    },
  },

  "learn/interrupted-stopped": {
    run: async (page) => {
      await fakeStream(page, "/api/learn/chat/stream", tokens(STREAM_TEXT), false);
      await openRecursion(page);
      await sendTurn(page, "Why does the call stack unwind in reverse order?");
      await expect(page.getByTestId("tutor-messages")).toContainText("Think of each recursive call", { timeout: 15_000 });
      await page.getByTestId("tutor-stop").click();
      await visible(page, "tutor-interrupted");
      await visible(page, "tutor-retry");
    },
  },

  "learn/interrupted-error": {
    run: async (page) => {
      await pinToasts(page);
      await fakeStream(
        page,
        "/api/learn/chat/stream",
        [...tokens(STREAM_TEXT.slice(0, 160)), sse("error", { retryable: true }, "reply", "The tutor was interrupted. Please retry.")],
        true,
      );
      await openRecursion(page);
      await sendTurn(page, "Why does the call stack unwind in reverse order?");
      await visible(page, "tutor-interrupted");
      await toast(page, "The tutor was interrupted");
    },
  },

  "learn/json-fallback-pending": {
    run: async (page) => {
      await hold(page, /^\/api\/learn\/chat$/);
      await page.route((url) => url.pathname.endsWith("/api/learn/chat/stream"), (route) => route.abort());
      await openRecursion(page);
      const msg = "What breaks without a base case?";
      await sendTurn(page, msg);
      await expect(page.getByTestId("tutor-messages")).toContainText(msg);
      await expect(page.getByTestId("tutor-stop")).toHaveCount(0, { timeout: 10_000 });
      await expect(page.getByTestId("tutor-messages")).not.toContainText("Thinking…");
      await expect(page.getByTestId("tutor-input")).toBeDisabled();
    },
  },

  "learn/action-loading": {
    run: async (page) => {
      await hold(page, "/api/learn/action");
      await openRecursion(page);
      await page.getByTestId("tutor-action-hint").click();
      await expect(page.getByTestId("tutor-messages")).toContainText("(Requested a hint)");
      await expect(page.getByTestId("tutor-messages")).toContainText("Thinking…");
    },
  },

  "learn/action-failed": {
    run: async (page) => {
      await pinToasts(page);
      await mockError(page, "/api/learn/action", 500, "Couldn't get a hint right now.");
      await openRecursion(page);
      await page.getByTestId("tutor-action-hint").click();
      await expect(page.getByRole("status").first()).toBeVisible({ timeout: 15_000 });
      await expect(page.getByTestId("tutor-messages")).not.toContainText("(Requested a hint)");
    },
  },

  "learn/mode-switched": {
    run: async (page) => {
      await mockJson(page, "/api/learn/mode-switch", {
        reply: "Switching to **Expository** mode — I'll explain recursion directly, with worked examples, then check your understanding.",
      });
      await openRecursion(page);
      await page.getByRole("button", { name: "Expository", exact: true }).click();
      await expect(page.getByTestId("tutor-messages")).toContainText("Switching to", { timeout: 15_000 });
      await text(page, /Expository Tutor ·/);
    },
  },

  "learn/mode-failed": {
    run: async (page) => {
      await pinToasts(page);
      await mockError(page, "/api/learn/mode-switch", 500, "Mode switch failed.");
      await openRecursion(page);
      await page.getByRole("button", { name: "Teach-back", exact: true }).click();
      await toast(page, "Mode switch failed.");
      await text(page, /Socratic Tutor ·/);
    },
  },

  "learn/model-fast": {
    run: async (page) => {
      await storage(page, { sapling_model_pref: "fast" });
      await openRecursion(page);
      await expect(page.getByRole("radio", { name: "Fast" })).toHaveAttribute("aria-checked", "true");
    },
  },

  "learn/model-smart": {
    run: async (page) => {
      await storage(page, { sapling_model_pref: "smart" });
      await openRecursion(page);
      await expect(page.getByRole("radio", { name: "Smart" })).toHaveAttribute("aria-checked", "true");
    },
  },

  "learn/model-tooltip": {
    run: async (page) => {
      await openRecursion(page);
      await page.getByRole("radiogroup", { name: "Tutor model" }).hover();
      await expect(page.getByRole("tooltip").filter({ hasText: "Tutor model" })).toBeVisible();
      await freeze(page);
    },
  },

  "learn/end-armed": {
    run: async (page) => {
      await pinArmed(page);
      await openRecursion(page);
      await page.getByRole("button", { name: "End session" }).click();
      await expect(page.getByRole("button", { name: "Confirm end" })).toBeVisible();
    },
  },

  "learn/summary-modal": {
    run: async (page) => {
      await mockJson(page, "/api/learn/end-session", { summary: SUMMARY });
      await openRecursion(page);
      await page.getByRole("button", { name: "End session" }).click();
      await page.getByRole("button", { name: "Confirm end" }).click();
      await text(page, "Nice session.");
      await text(page, "14 minutes spent.");
      await expect(page.getByRole("button", { name: "Tail Recursion" })).toBeVisible();
    },
  },

  "learn/summary-minimal": {
    run: async (page) => {
      await mockJson(page, "/api/learn/end-session", {
        summary: { concepts_covered: [], mastery_changes: [], new_connections: [], time_spent_minutes: 0, recommended_next: [] },
      });
      await openRecursion(page);
      await page.getByRole("button", { name: "End session" }).click();
      await page.getByRole("button", { name: "Confirm end" }).click();
      await text(page, "Session wrapped.");
      await expect(page.getByRole("button", { name: "Done" })).toBeVisible();
    },
  },

  "learn/end-failed": {
    run: async (page) => {
      await pinToasts(page);
      await mockError(page, "/api/learn/end-session", 500, "End session failed.");
      await openRecursion(page);
      await page.getByRole("button", { name: "End session" }).click();
      await page.getByRole("button", { name: "Confirm end" }).click();
      await toast(page, "End session failed.");
    },
  },

  "learn/markdown-rich": {
    run: async (page) => {
      await fakeStream(page, "/api/learn/chat/stream", finishedTurn(MARKDOWN_RICH), true);
      await openRecursion(page);
      await sendTurn(page, "Can you summarize recursion with an example?");
      const log = page.getByTestId("tutor-messages");
      await expect(log.locator("table").first()).toBeVisible({ timeout: 20_000 });
      await expect(log.locator(".katex").first()).toBeVisible();
      await expect(log.locator("pre code").first()).toBeVisible();
    },
  },

  "learn/markdown-mermaid": {
    run: async (page) => {
      await fakeStream(page, "/api/learn/chat/stream", finishedTurn(MARKDOWN_MERMAID), true);
      await openRecursion(page);
      await sendTurn(page, "Draw the call tree for factorial(3).");
      await expect(
        page.getByTestId("tutor-messages").getByRole("img", { name: /^Diagram:/ }).locator("svg").first(),
      ).toBeVisible({ timeout: 30_000 });
    },
  },

  "learn/markdown-plot": {
    run: async (page) => {
      await fakeStream(page, "/api/learn/chat/stream", finishedTurn(MARKDOWN_PLOT), true);
      await openRecursion(page);
      await sendTurn(page, "How fast does naive fibonacci grow?");
      await expect(
        page.getByTestId("tutor-messages").getByRole("img", { name: /^Function plot/ }).locator("svg").first(),
      ).toBeVisible({ timeout: 30_000 });
    },
  },

  "learn/rail-open-concept": {
    run: async (page) => {
      await openRecursion(page);
      await railReady(page);
      await text(page, "Knowledge map");
      await text(page, "Focused concept");
      await text(page, "In this branch");
      await text(page, "＋ Add concept");
    },
  },

  "learn/rail-focus-current": {
    run: async (page) => {
      await openRecursion(page);
      await railReady(page);
      await expect(page.getByRole("button", { name: "Remove", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: /^(Start|Resume) session$/ })).toHaveCount(0);
    },
  },

  "learn/rail-focus-other": {
    run: async (page) => {
      await openRecursion(page);
      await railReady(page);
      await page.locator('button[title="Focus Algorithms"]').first().click();
      await expect(page.getByRole("button", { name: /^(Start|Resume) session$/ })).toBeVisible();
      await expect(page.getByRole("button", { name: "Remove", exact: true })).toBeVisible();
    },
  },

  "learn/rail-tier-badges": {
    run: async (page) => {
      await openRecursion(page);
      await railReady(page);
      await page.locator('button[title="Focus Variables and Types"]').first().click();
      const card = page.getByText("Focused concept", { exact: true }).locator("..");
      await expect(card.getByText("Mastered", { exact: true })).toBeVisible();
    },
  },

  "learn/rail-desc-variants": {
    run: async (page) => {
      // AI blurb fails → the fallback "connected concepts" copy.
      await mockError(page, "/concept-description", 500);
      await openRecursion(page);
      await expect(page.getByTestId("tutor-focus-concept-description")).toContainText("connected concepts", {
        timeout: 30_000,
      });
    },
  },

  "learn/rail-focused-course": {
    run: async (page) => {
      await startFakeSession(page, "Exam review strategy", "CS101");
      await text(page, "Focused course");
      await expect(page.getByTestId("tutor-focus-concept-description")).toContainText("concepts in this course");
    },
  },

  "learn/rail-bare": {
    run: async (page) => {
      await startFakeSession(page, "How to take better lecture notes");
      await text(page, "Knowledge map");
      await expect(page.getByText("Focused course", { exact: true })).toHaveCount(0);
      await expect(page.getByText("Focused concept", { exact: true })).toHaveCount(0);
    },
  },

  "learn/rail-add-composer": {
    run: async (page) => {
      await openRecursion(page);
      await railReady(page);
      await page.getByRole("button", { name: "＋ Add concept" }).click();
      const input = page.getByPlaceholder("New concept name…");
      await input.fill("Tail Recursion");
      await expect(page.getByRole("button", { name: "Add", exact: true })).toBeEnabled();
      await freeze(page); // keep the input focused
    },
  },

  "learn/rail-add-merged": {
    run: async (page) => {
      await pinToasts(page);
      await mockJson(
        page,
        NODES,
        {
          node: { id: NODE_RECURSION, concept_name: "Recursion", course_id: COURSE_CS101, mastery_score: 0.25, mastery_tier: "struggling" },
          already_existed: true,
        },
        { method: "POST" },
      );
      await openRecursion(page);
      await railReady(page);
      await page.getByRole("button", { name: "＋ Add concept" }).click();
      // The shell's fixed "Report" button (FloatingActions, bottom-right)
      // sits over the rail's Add button at 1440×900 — submit with Enter,
      // which the composer input handles identically.
      const input = page.getByPlaceholder("New concept name…");
      await input.fill("recursion");
      await input.press("Enter");
      await toast(page, /Merged into your existing/);
    },
  },

  "learn/rail-add-failed": {
    run: async (page) => {
      await pinToasts(page);
      await mockError(page, NODES, 500, "Internal Server Error", "POST");
      await openRecursion(page);
      await railReady(page);
      await page.getByRole("button", { name: "＋ Add concept" }).click();
      // The shell's fixed "Report" button (FloatingActions, bottom-right)
      // sits over the rail's Add button at 1440×900 — submit with Enter,
      // which the composer input handles identically.
      const input = page.getByPlaceholder("New concept name…");
      await input.fill("Memoization");
      await input.press("Enter");
      await toast(page, "Couldn't save the concept — it was removed.");
    },
  },

  "learn/rail-streamed-node": {
    run: async (page) => {
      await fakeStream(
        page,
        "/api/learn/chat/stream",
        [
          sse("progress", null, "apply_graph_update_tool"),
          sse("graph_update", {
            nodes: { new_nodes: [{ concept_name: "Tail Recursion", initial_mastery: 0.1 }] },
            mastery_changes: [],
          }, "graph_update"),
          ...tokens("Nice — that idea has a name: tail recursion. I've added it to your map. "),
        ],
        false,
      );
      await openRecursion(page);
      await railReady(page);
      await sendTurn(page, "What if the recursive call is the very last thing the function does?");
      await expect(
        page.locator('[data-testid="graph-node-item"][data-node-id="stream-tail recursion"]'),
      ).toBeAttached({ timeout: 15_000 });
      await page.waitForTimeout(1_500); // let the new node settle into the layout
    },
  },

  "learn/rail-collapsed": {
    run: async (page) => {
      await storage(page, { sapling_learn_rail_open: "0" });
      await openRecursion(page);
      await expect(page.getByRole("button", { name: "Toggle knowledge map" })).toHaveAttribute("aria-expanded", "false");
      await page.waitForTimeout(600); // width transition
    },
  },

  "learn/rail-dragging": {
    run: async (page) => {
      await openRecursion(page);
      await railReady(page);
      const tab = page.getByRole("button", { name: "Toggle knowledge map" });
      const box = await tab.boundingBox();
      if (!box) throw new Error("rail tab has no box");
      const x = box.x + box.width / 2;
      const y = box.y + box.height / 2;
      await page.mouse.move(x, y);
      await page.mouse.down();
      await page.mouse.move(x + 80, y, { steps: 4 });
      await page.mouse.move(x + 160, y, { steps: 4 });
      await freeze(page);
      await expect(tab).toHaveCSS("cursor", "grabbing");
    },
  },

  "learn/suggest-highlight": {
    run: async (page) => {
      await page.goto("/learn?suggest=Algorithms");
      await page.getByTestId(`tutor-session-resume-${SESSION_RECURSION}`).click();
      await visible(page, "tutor-input");
      await railReady(page);
      const card = page.getByText("Focused concept", { exact: true }).locator("../..");
      await expect(card).toContainText("Algorithms");
      await expect(
        page.locator('[data-testid="graph-node"][data-node-id="rich-node-cs-algorithms"] animate').first(),
      ).toBeAttached();
    },
  },

  // ── /tree ───────────────────────────────────────────────────────────────
  "tree/loading": {
    run: async (page) => {
      await hold(page, GRAPH);
      await page.goto("/tree");
      await text(page, "0 nodes");
      await expect(page.locator(".skeleton").first()).toBeVisible({ timeout: 30_000 });
    },
  },

  "tree/populated": {
    run: async (page) => {
      await openTree(page);
      await visible(page, `graph-course-filter-${COURSE_CS101}`);
      await page.waitForTimeout(1_500);
    },
  },

  "tree/empty": {
    run: async (page) => {
      await mockJson(page, GRAPH, EMPTY_GRAPH);
      await mockJson(page, COURSES, { courses: [] }, { method: "GET" });
      await page.goto("/tree");
      await visible(page, "graph-container");
      await text(page, "0 nodes");
      await expect(page.getByRole("button", { name: "All courses" })).toBeVisible();
    },
  },

  "tree/search-filtered": {
    run: async (page) => {
      await openTree(page);
      await page.getByPlaceholder("Search concepts…").fill("re");
      await expect(page.locator('[data-testid="graph-node-item"][data-node-id="rich-node-cs-recursion"]')).toBeAttached();
      await expect(page.locator('[data-testid="graph-node-item"][data-node-id="rich-node-cs-variables"]')).toHaveCount(0);
      await page.waitForTimeout(1_500);
    },
  },

  "tree/filtered-zero": {
    run: async (page) => {
      await openTree(page);
      await page.getByPlaceholder("Search concepts…").fill("quantum chromodynamics");
      await text(page, "0 nodes");
      await expect(page.getByTestId("graph-node")).toHaveCount(0);
    },
  },

  "tree/tier-filtered": {
    run: async (page) => {
      await openTree(page);
      await page.getByRole("button", { name: "Struggling", exact: true }).click();
      await expect(page.locator(`[data-testid="graph-node-item"][data-node-id="${NODE_RECURSION}"]`)).toBeAttached();
      await expect(page.locator('[data-testid="graph-node-item"][data-node-id="rich-node-cs-variables"]')).toHaveCount(0);
      await page.waitForTimeout(1_500);
    },
  },

  "tree/course-filtered": {
    run: async (page) => {
      await treeCourse(page);
      await visible(page, "graph-add-concept");
      await page.waitForTimeout(1_500);
    },
  },

  "tree/add-concept-composer": {
    run: async (page) => {
      await treeCourse(page);
      await page.getByTestId("graph-add-concept").click();
      await page.getByTestId("graph-add-concept-input").fill("Tail Recursion");
      await expect(page.getByTestId("graph-add-concept-submit")).toBeEnabled();
      await freeze(page);
    },
  },

  "tree/toast-added": {
    run: async (page) => {
      await pinToasts(page);
      await mockJson(
        page,
        NODES,
        {
          node: { id: "fig-node-tail", concept_name: "Tail Recursion", course_id: COURSE_CS101, mastery_score: 0, mastery_tier: "unexplored" },
          already_existed: false,
        },
        { method: "POST" },
      );
      await treeCourse(page);
      await page.getByTestId("graph-add-concept").click();
      await page.getByTestId("graph-add-concept-input").fill("Tail Recursion");
      await page.getByTestId("graph-add-concept-submit").click();
      await toast(page, "Added “Tail Recursion”.");
    },
  },

  "tree/toast-merged": {
    run: async (page) => {
      await pinToasts(page);
      await mockJson(
        page,
        NODES,
        {
          node: { id: NODE_RECURSION, concept_name: "Recursion", course_id: COURSE_CS101, mastery_score: 0.25, mastery_tier: "struggling" },
          already_existed: true,
        },
        { method: "POST" },
      );
      await treeCourse(page);
      await page.getByTestId("graph-add-concept").click();
      await page.getByTestId("graph-add-concept-input").fill("recursion");
      await page.getByTestId("graph-add-concept-submit").click();
      await toast(page, /Merged into your existing/);
    },
  },

  "tree/toast-add-failed": {
    run: async (page) => {
      await pinToasts(page);
      await mockError(page, NODES, 500, "Internal Server Error", "POST");
      await treeCourse(page);
      await page.getByTestId("graph-add-concept").click();
      await page.getByTestId("graph-add-concept-input").fill("Memoization");
      await page.getByTestId("graph-add-concept-submit").click();
      await toast(page, "Couldn't add the concept.");
    },
  },

  "tree/checklist-loading": {
    run: async (page) => {
      await hold(page, CHECKLIST, "GET");
      await openChecklist(page);
      await text(page, "Updating checklist…");
      await visible(page, "topic-checklist-refresh");
    },
  },

  "tree/checklist-populated": {
    run: async (page) => {
      await mockJson(page, CHECKLIST, checklist(), { method: "GET" });
      await openChecklist(page);
      await visible(page, "topic-checklist-topic-fig-t-recursion");
      await visible(page, "topic-checklist-filter");
    },
  },

  "tree/checklist-semester-select": {
    run: async (page) => {
      // CS101 is enrolled in two terms and no semester is active → the extra select.
      await mockJson(page, CHECKLIST, checklist(), { method: "GET" });
      await openChecklist(page);
      await visible(page, "topic-checklist-topic-fig-t-recursion");
      await visible(page, "topic-checklist-semester");
    },
  },

  "tree/checklist-stale": {
    run: async (page) => {
      const stale = checklist({ needs_refresh: true });
      await mockJson(page, CHECKLIST, stale, { method: "GET" });
      await mockJson(page, CHECKLIST_REFRESH, stale, { method: "POST" });
      await openChecklist(page);
      await text(page, "Showing the previous outline. Update from materials to include recent changes.");
    },
  },

  "tree/checklist-warnings": {
    run: async (page) => {
      await mockJson(
        page,
        CHECKLIST,
        checklist({
          warnings: [
            "No syllabus uploaded for this course yet — topics come from the BU catalog description only.",
            "2 documents could not be read and were skipped.",
          ],
        }),
        { method: "GET" },
      );
      await openChecklist(page);
      await text(page, "2 documents could not be read and were skipped.");
    },
  },

  "tree/checklist-empty-filter": {
    run: async (page) => {
      await mockJson(
        page,
        CHECKLIST,
        checklist({ topics: CHECKLIST_TOPICS.filter((t) => t.status !== "mastered") }),
        { method: "GET" },
      );
      await openChecklist(page);
      await visible(page, "topic-checklist-topic-fig-t-recursion");
      await page.getByTestId("topic-checklist-filter").selectOption("mastered");
      await text(page, "No topics match this view.");
    },
  },

  "tree/checklist-error": {
    run: async (page) => {
      await mockError(page, CHECKLIST, 500, "Internal Server Error", "GET");
      await openChecklist(page);
      // Next's route announcer is also role="alert" — scope to the checklist's.
      await expect(
        page.getByRole("alert").filter({ hasText: "Could not update the checklist" }),
      ).toBeVisible({ timeout: 30_000 });
    },
  },

  "tree/detail-concept": {
    run: async (page) => {
      await openTree(page);
      await activateNode(page, NODE_RECURSION);
      await expect(page.getByRole("button", { name: "Learn this" })).toBeVisible();
      await visible(page, "tree-node-recent-quizzes");
      await expect(page.getByTestId("tree-node-recent-quizzes")).not.toContainText("Loading…", { timeout: 15_000 });
    },
  },

  "tree/detail-quizzes-loading": {
    run: async (page) => {
      await hold(page, ATTEMPTS);
      await openTree(page);
      await activateNode(page, NODE_RECURSION);
      await expect(page.getByTestId("tree-node-recent-quizzes")).toContainText("Loading…");
    },
  },

  "tree/detail-quizzes-empty": {
    run: async (page) => {
      await mockJson(page, ATTEMPTS, { total: 0, limit: 100, offset: 0, attempts: [] });
      await openTree(page);
      await activateNode(page, NODE_RECURSION);
      await expect(page.getByTestId("tree-node-recent-quizzes")).toContainText("No quizzes yet");
    },
  },

  "tree/detail-quizzes-rows": {
    run: async (page) => {
      await mockJson(page, ATTEMPTS, {
        total: 3,
        limit: 100,
        offset: 0,
        attempts: [
          attempt("fig-qa-3", 4, 5, 0.12, "2026-03-10T18:00:00Z"),
          attempt("fig-qa-2", 3, 5, 0.05, "2026-03-07T14:30:00Z"),
          attempt("fig-qa-1", 2, 5, -0.03, "2026-03-02T09:15:00Z"),
        ],
      });
      await openTree(page);
      await activateNode(page, NODE_RECURSION);
      await visible(page, "tree-node-recent-quiz-fig-qa-3");
      await visible(page, "tree-node-recent-quiz-fig-qa-1");
    },
  },

  "tree/detail-delete-armed": {
    run: async (page) => {
      await pinArmed(page);
      await openTree(page);
      await activateNode(page, NODE_RECURSION);
      await page.getByRole("button", { name: "Delete concept" }).click();
      await expect(page.getByRole("button", { name: "Click again to confirm" })).toBeVisible();
    },
  },

  "tree/toast-deleted": {
    run: async (page) => {
      await pinToasts(page);
      await mockJson(page, NODE_ITEM, { deleted: true }, { method: "DELETE" });
      await openTree(page);
      await activateNode(page, NODE_RECURSION);
      await page.getByRole("button", { name: "Delete concept" }).click();
      await page.getByRole("button", { name: "Click again to confirm" }).click();
      await toast(page, 'Deleted "Recursion".');
    },
  },

  "tree/toast-delete-failed": {
    run: async (page) => {
      await pinToasts(page);
      await mockError(page, NODE_ITEM, 500, "Internal Server Error", "DELETE");
      await openTree(page);
      await activateNode(page, NODE_RECURSION);
      await page.getByRole("button", { name: "Delete concept" }).click();
      await page.getByRole("button", { name: "Click again to confirm" }).click();
      await toast(page, /^Delete failed:/);
    },
  },

  "tree/detail-subject-root": {
    run: async (page) => {
      await openTree(page);
      await activateNode(page, `subject_root__${COURSE_CS101}`);
      await expect(page.getByRole("button", { name: "Learn this" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Delete concept" })).toHaveCount(0);
      await expect(page.getByTestId("tree-node-recent-quizzes")).toHaveCount(0);
    },
  },

  "tree/node-param": {
    run: async (page) => {
      await openTree(page, `/tree?node=${NODE_RECURSION}`);
      await expect(page.getByRole("button", { name: "Learn this" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Recursion" })).toBeVisible();
    },
  },

  "tree/suggest-param": {
    run: async (page) => {
      await openTree(page, "/tree?suggest=Recursion");
      await expect(page.getByRole("heading", { name: "Recursion" })).toBeVisible();
      await expect(
        page.locator(`[data-testid="graph-node"][data-node-id="${NODE_RECURSION}"] animate`).first(),
      ).toBeAttached();
    },
  },

  "tree/fullscreen": {
    run: async (page) => {
      await openTree(page);
      await page.getByRole("button", { name: "Fullscreen", exact: true }).click();
      await text(page, "Knowledge tree — fullscreen");
      await waitGraph(page);
    },
  },
};
