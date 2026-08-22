// @vitest-environment jsdom
/**
 * `QuizScreen` end to end against mocked clients, for the one question a hook
 * test cannot answer: what the WHOLE screen does to the URL when the student
 * presses Done.
 *
 * The browser lane found Done leaving `?concept=…` in the address bar through
 * two fixes (`router.push`, then `router.replace`), so the useful assertion is
 * not "we called the router" — it is "exactly one URL change happened, it was to
 * a clean `/quiz`, and nothing afterwards put the deep link back".
 */

import React from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AnswerResult, GenerateResult, SubmitResult } from "@/lib/quiz/types";

// ── next/navigation ────────────────────────────────────────────────────────
let searchParams = new URLSearchParams();
let pathname = "/quiz";
const push = vi.fn();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams,
  usePathname: () => pathname,
  useRouter: () => ({ push, replace, back: vi.fn(), prefetch: vi.fn() }),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

const quizApi = vi.hoisted(() => ({
  fetchQuizConfig: vi.fn(),
  generateQuiz: vi.fn(),
  answerQuestion: vi.fn(),
  submitQuiz: vi.fn(),
  getAttempt: vi.fn(),
  listAttempts: vi.fn(),
  describeConcept: vi.fn(),
}));
vi.mock("@/lib/quiz/api", () => quizApi);

const coreApi = vi.hoisted(() => ({
  getCourses: vi.fn(),
  getGraph: vi.fn(),
  fetchGamificationMe: vi.fn(),
}));
vi.mock("@/lib/api", async importActual => {
  const actual = await importActual<typeof import("@/lib/api")>();
  return { ...actual, ...coreApi };
});

import { QuizScreen } from "./QuizScreen";
import { ToastProvider } from "@/components/ToastProvider";

const CONFIG = {
  num_questions: { min: 1, max: 10, options: [3, 5, 10] },
  difficulties: ["easy", "medium", "hard", "adaptive"],
  question_types: ["multiple_choice"],
};

const NODES = [
  {
    id: "c1", concept_name: "Recursion", mastery_score: 0.25, mastery_tier: "struggling",
    times_studied: 2, last_studied_at: "2026-08-18T00:00:00Z", subject: "CS",
    course_id: "course-a",
  },
  {
    id: "c2", concept_name: "Big-O", mastery_score: 0.44, mastery_tier: "learning",
    times_studied: 1, last_studied_at: "2026-08-19T00:00:00Z", subject: "CS",
    course_id: "course-a",
  },
];

const COURSES = [{
  enrollment_id: "e1", course_id: "course-a", course_code: "CS 330",
  course_name: "Algorithms", school: "BU", department: "CS", color: "#123456",
  nickname: null, node_count: 2, enrolled_at: "2026-01-01T00:00:00Z",
  term: "Fall 2026", terms: ["Fall 2026"],
}];

const GENERATED: GenerateResult = {
  quiz_id: "attempt-1",
  questions: [{
    id: 1,
    question: "What is recursion?",
    options: [
      { label: "A", text: "a" }, { label: "B", text: "b" },
      { label: "C", text: "c" }, { label: "D", text: "d" },
    ],
    difficulty: "medium",
  }],
  requested_difficulty: "medium",
  resolved_difficulty: "medium",
  requested_count: 1,
  delivered_count: 1,
};

const ANSWER: AnswerResult = {
  question_index: 0, question_id: 1, is_correct: true, correct_index: 1,
  explanation: "because", next_question: null, recorded: true,
};

const SUBMITTED: SubmitResult = {
  score: 1, total: 1, mastery_before: 0.25, mastery_after: 0.34, results: [],
};

/**
 * Every way the app can change the address bar, in the order it happened.
 * `router.push`/`replace` are spies; the History API is patched so a direct
 * `replaceState` is caught too — the point of the test is that we do not care
 * WHICH mechanism moved the URL, only that it moved once and landed clean.
 */
let navigations: { via: string; url: string }[] = [];
const realReplaceState = window.history.replaceState.bind(window.history);
const realPushState = window.history.pushState.bind(window.history);

beforeEach(() => {
  // Put jsdom where the student actually is. `exit` reads
  // `window.location.pathname` to tell "same route" from "real navigation", so a
  // test left on jsdom's default "/" would exercise the wrong branch. Done
  // before the spies go on, so this setup is not counted as a navigation.
  window.history.replaceState(null, "", "/quiz?concept=c1&from=link");

  navigations = [];
  searchParams = new URLSearchParams("concept=c1&from=link");
  pathname = "/quiz";
  window.localStorage.clear();
  window.localStorage.setItem("sapling_disclaimer_ack", "true");

  push.mockReset().mockImplementation((url: string) => navigations.push({ via: "push", url }));
  replace.mockReset().mockImplementation((url: string) => navigations.push({ via: "replace", url }));
  vi.spyOn(window.history, "replaceState").mockImplementation((s, t, url) => {
    if (typeof url === "string") navigations.push({ via: "history.replaceState", url });
    return realReplaceState(s, t, url as string);
  });
  vi.spyOn(window.history, "pushState").mockImplementation((s, t, url) => {
    if (typeof url === "string") navigations.push({ via: "history.pushState", url });
    return realPushState(s, t, url as string);
  });

  // jsdom has no matchMedia; `usePrefersReducedMotion` reads it during render.
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false, media: query, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    }),
  });

  quizApi.fetchQuizConfig.mockResolvedValue(CONFIG);
  quizApi.generateQuiz.mockResolvedValue(GENERATED);
  quizApi.answerQuestion.mockResolvedValue(ANSWER);
  quizApi.submitQuiz.mockResolvedValue(SUBMITTED);
  quizApi.listAttempts.mockResolvedValue({ total: 0, limit: 20, offset: 0, attempts: [] });
  quizApi.getAttempt.mockResolvedValue({ resumable: false });
  quizApi.describeConcept.mockResolvedValue("Recursion is a function calling itself.");
  coreApi.getCourses.mockResolvedValue({ courses: COURSES });
  coreApi.getGraph.mockResolvedValue({ nodes: NODES, edges: [], stats: {} });
  coreApi.fetchGamificationMe.mockRejectedValue(new Error("not under test"));
});

afterEach(() => {
  // vitest runs with globals:false, so testing-library auto-cleanup never hooks
  // in — without this every render stacks and getByTestId finds duplicates.
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

/** Home → start → answer the single question → results. */
async function playToResults(): Promise<void> {
  render(
    <ToastProvider>
      <QuizScreen />
    </ToastProvider>,
  );

  const start = await screen.findByTestId("quiz-start", undefined, { timeout: 3000 });
  await act(async () => {
    start.click();
  });

  const optionA = await screen.findByTestId("quiz-answer-option-A", undefined, { timeout: 3000 });
  await act(async () => {
    optionA.click();
  });
  await act(async () => {
    screen.getByTestId("quiz-submit-answer").click();
  });

  await waitFor(() => expect(screen.getByTestId("quiz-results")).toBeTruthy(), { timeout: 3000 });
}

describe("QuizScreen — Done drops the deep link (#537)", () => {
  it("changes the URL exactly once, to a clean /quiz", async () => {
    await playToResults();
    expect(navigations).toEqual([]);
    expect(location.pathname + location.search).toBe("/quiz?concept=c1&from=link");

    await act(async () => {
      screen.getByTestId("quiz-done").click();
    });

    expect(navigations).toHaveLength(1);
    expect(navigations[0].url).toBe("/quiz");
    // The assertion the browser lane makes, and the one that was failing: the
    // address bar itself, not the call we hoped would move it.
    expect(location.pathname + location.search).toBe("/quiz");
  });

  it("never re-issues the deep link afterwards", async () => {
    await playToResults();
    await act(async () => {
      screen.getByTestId("quiz-done").click();
    });

    // Let every effect that could re-sync the URL from the entry or the session
    // settle — the lane's symptom was the query coming BACK, not never leaving.
    await act(async () => {
      await new Promise(r => setTimeout(r, 50));
    });

    for (const nav of navigations) {
      expect(nav.url, `${nav.via} re-issued the deep link`).not.toContain("concept=");
    }
    expect(navigations).toHaveLength(1);
  });

  it("does not ask the router to navigate to the route it is already on", async () => {
    await playToResults();
    await act(async () => {
      screen.getByTestId("quiz-done").click();
    });

    // A route-tree-identical navigation is not a navigation; asking the router
    // for one is what silently did nothing twice (push, then replace). The URL
    // edit goes through the History API, which is what Next supports for a
    // search-param change in place.
    expect(push).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
    expect(navigations.map(n => n.via)).toEqual(["history.replaceState"]);
  });

  it("lands back on quiz home with no results on screen", async () => {
    await playToResults();
    await act(async () => {
      screen.getByTestId("quiz-done").click();
    });

    await waitFor(() => expect(screen.queryByTestId("quiz-results")).toBeNull());
    expect(screen.getByTestId("quiz-home")).toBeTruthy();
  });

  it("still uses the router for an exit that really changes route", async () => {
    await playToResults();
    await act(async () => {
      screen.getByTestId("quiz-back-to-source").click();
    });

    // `from=link` with no `return`, so R-10 falls back to the tree focused on
    // the concept — a real route change, and the router's job.
    expect(navigations).toEqual([{ via: "push", url: "/tree?node=c1" }]);
    // …and the History API is NOT used to fake a cross-route move.
    expect(location.pathname).toBe("/quiz");
  });
});
