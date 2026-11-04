// @vitest-environment jsdom
/**
 * Quiz home (§5 B1) — the behaviour the screen is specified by.
 *
 * The fixtures build the `useQuizHome` shape with the REAL `lib/quiz/proposals`
 * functions rather than hand-written candidate lists: the ranking, the due set
 * and the grouping are the hook's own, so a test that hand-rolled them would
 * pass while the screen showed something else.
 *
 * What is pinned here:
 *   - the resume strip, its Resume, and its Discard (R-3 / G4)
 *   - Start's request shape and the config it carries
 *   - the due row's queue cap and per-attempt count (R-4)
 *   - the concept dialog opening off an alternative, and starting with ITS config
 *   - Adjust's Done writing settings back without starting
 *   - `?concept=` overriding the ranked proposal, and an unresolved one toasting once
 *   - both empty states, and that neither is a dead end
 *   - that every option list comes off `/config` — the counts and difficulties
 *     below are deliberately NOT the server's real ones
 */

import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";
import type { GraphEdge, GraphNode } from "@/lib/types";
import {
  alternativesOf,
  dueSet,
  groupByCourse,
  primaryOf,
  rankCandidates,
} from "@/lib/quiz/proposals";
import { QUEUE_COUNT } from "@/lib/quiz/session";
import type { EntryRequest } from "@/lib/quiz/source";
import type { QuizHome as QuizHomeData } from "@/lib/quiz/useQuizHome";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import { __resetReducedMotionStoreForTests } from "@/lib/usePrefersReducedMotion";
import type {
  AttemptDetail,
  AttemptSummary,
  QuizConfig,
  QuizSession,
  WireQuestion,
} from "@/lib/quiz/types";
import { QuizHome } from "./QuizHome";

// ── Mocks ────────────────────────────────────────────────────────────────

const toast = vi.hoisted(() => ({
  show: vi.fn(),
  dismiss: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warn: vi.fn(),
}));

vi.mock("@/components/ToastProvider", () => ({ useToast: () => toast }));

// R-8's per-concept sentence. Resolved empty so the dialog renders its built
// fallback deterministically, with no floating network promise.
vi.mock("@/lib/quiz/api", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/quiz/api")>()),
  describeConcept: vi.fn().mockResolvedValue(""),
}));

// ── Fixtures ─────────────────────────────────────────────────────────────

/** Two courses; the prototype's own pair. */
const COURSES: EnrolledCourse[] = [
  course("c-cs", "CS101", "Intro to Computer Science", "#7b4b99"),
  course("c-math", "MATH210", "Linear Algebra", "#3e6f8a"),
];

function course(id: string, code: string, name: string, color: string): EnrolledCourse {
  return {
    enrollment_id: `e-${id}`,
    course_id: id,
    course_code: code,
    course_name: name,
    school: "Test University",
    department: "TEST",
    color,
    nickname: null,
    node_count: 4,
    enrolled_at: "2026-01-01T00:00:00Z",
    term: "Spring 2026",
  };
}

function node(
  id: string,
  name: string,
  courseId: string,
  mastery: number,
  tier: GraphNode["mastery_tier"],
  timesStudied: number,
): GraphNode {
  return {
    id,
    concept_name: name,
    mastery_score: mastery,
    mastery_tier: tier,
    times_studied: timesStudied,
    last_studied_at: timesStudied > 0 ? "2026-08-18T00:00:00Z" : null,
    subject: courseId === "c-cs" ? "Intro to Computer Science" : "Linear Algebra",
    course_id: courseId,
    is_subject_root: false,
  };
}

/** Seven due concepts across two courses — enough to prove the queue cap. */
const NODES: GraphNode[] = [
  node("recursion", "Recursion", "c-cs", 0.29, "struggling", 3),
  node("base-cases", "Base cases", "c-cs", 0.52, "learning", 1),
  node("stack-frames", "Stack frames", "c-cs", 0.3, "struggling", 0),
  node("tail-recursion", "Tail recursion", "c-cs", 0.12, "struggling", 0),
  node("eigenvalues", "Eigenvalues", "c-math", 0.31, "struggling", 1),
  node("matrices", "Matrices", "c-math", 0.44, "struggling", 2),
  node("determinants", "Determinants", "c-math", 0.05, "unexplored", 0),
];

const EDGES: GraphEdge[] = [
  { id: "e1", source: "recursion", target: "base-cases", strength: 0.9 },
  { id: "e2", source: "recursion", target: "stack-frames", strength: 0.7 },
  { id: "e3", source: "recursion", target: "tail-recursion", strength: 0.4 },
  { id: "e4", source: "eigenvalues", target: "matrices", strength: 0.8 },
];

/**
 * Deliberately NOT the server's real lists: if any option row is hardcoded
 * rather than read off `/config`, "2 questions" and "gentle" disappear and a
 * 3/5/10 or "medium" shows up instead.
 */
const CONFIG: QuizConfig = {
  num_questions: { min: 2, max: 4, options: [2, 4] },
  difficulties: ["gentle", "fierce"],
  question_types: ["multiple_choice"],
};

const SESSION_CONFIG = { count: 2, difficulty: "gentle", feedback: "at-end" as const };

function session(over: Partial<QuizSession> = {}): QuizSession {
  return {
    intent: "practice",
    scope: { kind: "concept", conceptId: "" },
    source: { kind: "nav" },
    config: SESSION_CONFIG,
    conceptId: "",
    courseId: null,
    attemptId: null,
    items: [],
    cursor: 0,
    queueIndex: 0,
    phase: "home",
    error: null,
    result: null,
    xp: null,
    deliveredShort: false,
    sourceAttemptId: null,
    reserved: null,
    ...over,
  };
}

function entry(over: Partial<EntryRequest> = {}): EntryRequest {
  return { source: { kind: "nav" }, ...over };
}

function question(id: number): WireQuestion {
  return {
    id,
    question: `Question ${id}`,
    options: [{ label: "A", text: "one" }],
    difficulty: "gentle",
  };
}

function attemptDetail(over: Partial<AttemptDetail> = {}): AttemptDetail {
  return {
    quiz_id: "attempt-1",
    status: "in_progress",
    resumable: true,
    difficulty: "gentle",
    concept_node_id: "recursion",
    questions: [question(1), question(2), question(3), question(4), question(5)],
    responses: [
      { question_index: 0, selected_index: 1, is_correct: true, answered_at: "2026-08-22T00:00:00Z" },
      { question_index: 1, selected_index: 0, is_correct: false, answered_at: "2026-08-22T00:01:00Z" },
    ],
    score: null,
    total: null,
    created_at: "2026-08-22T00:00:00Z",
    ...over,
  };
}

function buildHome(over: Partial<QuizHomeData> = {}): QuizHomeData {
  const nodes = over.nodes ?? NODES;
  const courses = over.courses ?? COURSES;
  const attempts: AttemptSummary[] = over.attempts ?? [];
  const candidates = rankCandidates(nodes, courses, attempts);
  const primary = primaryOf(candidates);
  return {
    status: "ready",
    error: null,
    nodes,
    edges: over.edges ?? EDGES,
    courses,
    attempts,
    candidates,
    primary,
    alternatives: alternativesOf(candidates, primary),
    due: dueSet(nodes),
    byCourse: groupByCourse(nodes, courses),
    resumable: null,
    // A2 fix round 5: the hook now describes the concept the CARD shows, which a
    // deep link overrides. `primaryDescription` is a deprecated alias.
    cardConceptId: primary?.node.id ?? null,
    cardDescription: null,
    primaryDescription: null,
    // Settled by default: a failed or finished fetch, so the built sentence
    // shows; the in-flight placeholder has its own test.
    cardDescriptionPending: false,
    prefetchDescription: vi.fn(),
    refresh: vi.fn(),
    discard: vi.fn(),
    ...over,
  };
}

function buildActions(): QuizActions {
  return {
    configure: vi.fn(),
    setConfig: vi.fn(),
    start: vi.fn(),
    select: vi.fn(),
    submitAnswer: vi.fn(),
    next: vi.fn(),
    finish: vi.fn(),
    requestLeave: vi.fn(),
    cancelLeave: vi.fn(),
    confirmLeave: vi.fn(),
    resume: vi.fn(),
    practiseMissed: vi.fn(),
    nextInQueue: vi.fn(),
    exit: vi.fn(),
    flag: vi.fn(),
    dismissError: vi.fn(),
    retry: vi.fn(),
  };
}

function mount(
  over: {
    home?: Partial<QuizHomeData>;
    entry?: EntryRequest;
    config?: QuizConfig | null;
    /** The live session. Cancel reads `session.source`, NOT the entry's. */
    session?: QuizSession;
  } = {},
) {
  const home = buildHome(over.home);
  const actions = buildActions();
  const onPickedChange = vi.fn();
  const view = render(
    <QuizHome
      userId="u1"
      home={home}
      config={over.config === undefined ? CONFIG : over.config}
      entry={over.entry ?? entry()}
      session={over.session ?? session()}
      actions={actions}
      onPickedChange={onPickedChange}
    />,
  );
  return { home, actions, view, onPickedChange };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
  window.localStorage.clear();
});

// ── Tests ────────────────────────────────────────────────────────────────

describe("QuizHome — the proposal", () => {
  it("offers the ranked primary and starts it with the session config", () => {
    const { actions } = mount();

    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent("Recursion");
    // The config line is read, not written: [2, 4] / gentle came off `/config`.
    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent("2 questions, gentle");

    fireEvent.click(screen.getByTestId("quiz-start"));

    expect(actions.start).toHaveBeenCalledWith(
      {
        intent: "practice",
        scope: { kind: "concept", conceptId: "recursion" },
        conceptId: "recursion",
        courseId: "c-cs",
      },
      SESSION_CONFIG,
    );
  });

  it("captions a deep-linked card with the sentence fetched for THAT concept", () => {
    // The hook describes the concept the CARD shows, deep link included (A2 fix
    // round 5) — so the paragraph belongs to Matrices, not to the ranked primary.
    mount({
      home: { cardConceptId: "matrices", cardDescription: "A rectangular array of numbers." },
      entry: entry({ concept: "matrices", source: { kind: "tree" } }),
    });

    const proposal = screen.getByTestId("quiz-proposal");
    expect(proposal).toHaveTextContent("Matrices");
    expect(proposal).toHaveTextContent("A rectangular array of numbers.");
  });

  it("holds a placeholder, not a stand-in sentence, while the description is in flight", () => {
    // Showing the built sentence and then replacing it a moment later read as
    // a glitch; the stand-in is only for a fetch that failed.
    mount({ home: { cardDescription: null, cardDescriptionPending: true } });

    const proposal = screen.getByTestId("quiz-proposal");
    expect(screen.getByTestId("quiz-definition-pending")).toBeInTheDocument();
    expect(proposal).not.toHaveTextContent("connected concepts");
  });

  it("falls back to the built sentence when the description could not be fetched", () => {
    mount({ home: { cardDescription: null, cardDescriptionPending: false } });

    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent(
      "CS101 · struggling · 3 connected concepts",
    );
  });

  it("warms a row's description once the student rests on it, not on a sweep", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { home } = mount();
    // A pass over a row on the way somewhere else costs nothing.
    fireEvent.pointerEnter(screen.getByTestId("quiz-pick-eigenvalues"));
    fireEvent.pointerLeave(screen.getByTestId("quiz-pick-eigenvalues"));
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(home.prefetchDescription).not.toHaveBeenCalled();

    fireEvent.pointerEnter(screen.getByTestId("quiz-pick-determinants"));
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(home.prefetchDescription).toHaveBeenCalledWith("determinants");

    fireEvent.focus(screen.getByTestId("quiz-pick-base-cases"));
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(home.prefetchDescription).toHaveBeenCalledWith("base-cases");
    expect(home.prefetchDescription).toHaveBeenCalledTimes(2);
  });

  it("does not let the pointer leaving one row cancel keyboard focus on another", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { home } = mount();
    fireEvent.focus(screen.getByTestId("quiz-pick-base-cases"));
    fireEvent.pointerEnter(screen.getByTestId("quiz-pick-eigenvalues"));
    fireEvent.pointerLeave(screen.getByTestId("quiz-pick-eigenvalues"));
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(home.prefetchDescription).toHaveBeenCalledWith("base-cases");
    expect(home.prefetchDescription).not.toHaveBeenCalledWith("eigenvalues");
  });

  it("cancels back to the session's source", () => {
    // `cancelTarget` reads `session.source.returnTo`. A session that carries one
    // must land there — not on the fallback the no-source case uses.
    const { actions } = mount({
      session: session({ source: { kind: "tree", returnTo: "/tree?node=recursion" } }),
    });
    fireEvent.click(screen.getByTestId("quiz-cancel"));
    expect(actions.exit).toHaveBeenCalledWith("/tree?node=recursion");
  });

  it("cancels to the dashboard when the session has no source", () => {
    // The fixture session is `{kind:"nav"}` with no `returnTo` (§5 B1.8).
    const { actions } = mount();
    fireEvent.click(screen.getByTestId("quiz-cancel"));
    expect(actions.exit).toHaveBeenCalledWith("/dashboard");
  });

  it("keeps Cancel reachable when there is nothing to propose", () => {
    // The three no-card states are still a way back to wherever you came from.
    const { actions } = mount({
      home: { nodes: [], edges: [] },
      session: session({ source: { kind: "tree", returnTo: "/tree?node=recursion" } }),
    });

    expect(screen.getByTestId("quiz-empty-state")).toHaveTextContent("Your tree is empty");
    fireEvent.click(screen.getByTestId("quiz-cancel"));
    expect(actions.exit).toHaveBeenCalledWith("/tree?node=recursion");
  });
});

describe("QuizHome — the resume strip", () => {
  it("names the concept and resumes the attempt", () => {
    const { actions } = mount({
      home: { resumable: { attempt: attemptDetail(), session: null, answered: 2 } },
    });

    const strip = screen.getByTestId("quiz-resume-strip");
    expect(strip).toHaveTextContent("You left a quiz on Recursion — 2 of 5 answered");

    fireEvent.click(within(strip).getByTestId("quiz-resume"));
    expect(actions.resume).toHaveBeenCalledWith("attempt-1");
  });

  it("hands Discard to the hook, which abandons it server-side (G4)", () => {
    // The screen states the intent and nothing else: hiding the row locally,
    // the abandon call and the reload are one operation, and splitting them
    // across the component is how they drifted apart before (the row used to
    // be hidden here and never closed anywhere).
    const { home } = mount({
      home: { resumable: { attempt: attemptDetail(), session: null, answered: 2 } },
    });

    fireEvent.click(screen.getByTestId("quiz-resume-discard"));

    expect(home.discard).toHaveBeenCalledWith("attempt-1");
  });

  it("is absent when nothing is resumable", () => {
    mount();
    expect(screen.queryByTestId("quiz-resume-strip")).toBeNull();
  });
});

describe("QuizHome — the due row", () => {
  it("starts a capped queue of short attempts (R-4)", () => {
    const { actions } = mount();

    const row = screen.getByTestId("quiz-review-due");
    expect(row).toHaveTextContent("7 concepts across 2 courses");

    fireEvent.click(row);

    const [request, config] = (actions.start as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(request.intent).toBe("review");
    expect(request.scope.kind).toBe("due");
    // Seven concepts are due; a session runs at most QUEUE_MAX of them.
    expect(request.scope.queue).toHaveLength(5);
    // Weakest first, and the first one is what generates.
    expect(request.scope.queue[0]).toBe("determinants");
    expect(request.conceptId).toBe("determinants");
    expect(config.count).toBe(QUEUE_COUNT);
  });

  it("is hidden when nothing is due", () => {
    const mastered = NODES.map(n => ({ ...n, mastery_tier: "mastered" as const }));
    mount({ home: { nodes: mastered } });
    expect(screen.queryByTestId("quiz-review-due")).toBeNull();
  });
});

describe("QuizHome — picking a concept", () => {
  it("makes a topic row the card, and Start acts on it", () => {
    const { actions, onPickedChange } = mount();

    fireEvent.click(screen.getByTestId("quiz-pick-determinants"));

    expect(screen.getByTestId("quiz-proposal-name")).toHaveTextContent("Determinants");
    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent("Your pick");
    // No dialog: the card beside the list is where it is started from.
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onPickedChange).toHaveBeenLastCalledWith("determinants");

    fireEvent.click(screen.getByTestId("quiz-start"));
    expect(actions.start).toHaveBeenCalledWith(
      {
        intent: "practice",
        scope: { kind: "concept", conceptId: "determinants" },
        conceptId: "determinants",
        courseId: "c-math",
      },
      SESSION_CONFIG,
    );
  });

  it("swaps the list too: the picked row leaves, the old card's concept returns, tinted once", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    mount();
    fireEvent.click(screen.getByTestId("quiz-pick-determinants"));

    const list = screen.getByTestId("quiz-pick-list");
    expect(within(list).queryByTestId("quiz-pick-determinants")).toBeNull();
    expect(within(list).getByTestId("quiz-pick-recursion")).toHaveAttribute("data-returned", "true");
    // The tint runs once; a later re-render of the list must not replay it.
    act(() => {
      vi.advanceTimersByTime(1400);
    });
    expect(within(screen.getByTestId("quiz-pick-list")).getByTestId("quiz-pick-recursion")).not.toHaveAttribute(
      "data-returned",
    );
  });

  it("plays the card's entrance on a swap, not on arrival", () => {
    // Motion allowed, explicitly: the entrance is skipped under "reduce".
    const original = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }) as unknown as typeof window.matchMedia;
    __resetReducedMotionStoreForTests();
    mount();
    expect(screen.getByTestId("quiz-proposal")).not.toHaveAttribute("data-entering");
    fireEvent.click(screen.getByTestId("quiz-pick-determinants"));
    expect(screen.getByTestId("quiz-proposal")).toHaveAttribute("data-entering", "true");
    window.matchMedia = original;
    __resetReducedMotionStoreForTests();
  });

  it("opens Adjust on the picked concept", () => {
    mount();
    fireEvent.click(screen.getByTestId("quiz-pick-base-cases"));
    fireEvent.click(screen.getByTestId("quiz-adjust"));
    expect(screen.getByTestId("quiz-adjust-dialog")).toHaveTextContent("Base cases · CS101");
  });

  it("goes back to the suggestion", () => {
    const { onPickedChange } = mount();
    fireEvent.click(screen.getByTestId("quiz-pick-determinants"));
    fireEvent.click(screen.getByTestId("quiz-pick-reset"));

    expect(screen.getByTestId("quiz-proposal-name")).toHaveTextContent("Recursion");
    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent("Ready for you");
    expect(screen.queryByTestId("quiz-pick-reset")).toBeNull();
    expect(onPickedChange).toHaveBeenLastCalledWith(null);
  });

  it("treats picking the suggested concept back as returning to the suggestion", () => {
    mount();
    fireEvent.click(screen.getByTestId("quiz-pick-determinants"));
    // Recursion — the suggestion — is back in the list; picking it is "back".
    fireEvent.click(screen.getByTestId("quiz-pick-recursion"));
    expect(screen.getByTestId("quiz-proposal-name")).toHaveTextContent("Recursion");
    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent("Ready for you");
    expect(screen.queryByTestId("quiz-pick-reset")).toBeNull();
  });

  it("lets a queue card's first concept be picked, and Back returns to the queue", () => {
    mount({ entry: entry({ course: "c-cs", source: { kind: "dashboard" } }) });
    expect(screen.getByTestId("quiz-proposal-name")).toHaveTextContent("Practice CS101");

    // The queue opens on Tail recursion, which stays in the list; picking it
    // must do something.
    fireEvent.click(screen.getByTestId("quiz-pick-tail-recursion"));
    expect(screen.getByTestId("quiz-proposal-name")).toHaveTextContent("Tail recursion");
    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent("Your pick");

    fireEvent.click(screen.getByTestId("quiz-pick-reset"));
    expect(screen.getByTestId("quiz-proposal-name")).toHaveTextContent("Practice CS101");
  });

  it("drops a deep link's reason once the student picks something else", () => {
    mount({ entry: entry({ concept: "matrices", source: { kind: "notes", noteId: "n1" } }) });
    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent("From your note");
    fireEvent.click(screen.getByTestId("quiz-pick-determinants"));
    expect(screen.getByTestId("quiz-proposal")).not.toHaveTextContent("From your note");
  });

  it("holds the definition's placeholder until the hook has described the pick", () => {
    // The hook describes ITS card, and catches up with a pick a render later;
    // until then there is no sentence to show for the new concept.
    mount();
    fireEvent.click(screen.getByTestId("quiz-pick-base-cases"));
    expect(screen.getByTestId("quiz-definition-pending")).toBeInTheDocument();
  });

  it("lists each course weakest first, without the concept already proposed", () => {
    mount();

    const list = screen.getByTestId("quiz-pick-list");
    const ids = Array.from(list.querySelectorAll("[data-testid^='quiz-pick-']")).map(el =>
      el.getAttribute("data-testid"),
    );
    // Recursion is on the card, so it is not offered again beside it. Each
    // row carries the same meta line as the card.
    expect(ids).toEqual([
      "quiz-pick-tail-recursion",
      "quiz-pick-stack-frames",
      "quiz-pick-base-cases",
      "quiz-pick-determinants",
      "quiz-pick-eigenvalues",
      "quiz-pick-matrices",
    ]);
    expect(within(list).getByTestId("quiz-pick-base-cases")).toHaveTextContent("52% · learning");
  });

  it("draws no course heading when there is only one course", () => {
    const csOnly = NODES.filter(n => n.course_id === "c-cs");
    mount({ home: { nodes: csOnly } });

    const list = screen.getByTestId("quiz-pick-list");
    expect(within(list).queryByText("CS101 · Intro to Computer Science")).toBeNull();
    expect(within(list).getByTestId("quiz-pick-base-cases")).toBeInTheDocument();
  });
});

describe("QuizHome — searching the topic list", () => {
  const search = (q: string) =>
    fireEvent.change(screen.getByTestId("quiz-topic-search"), { target: { value: q } });
  const rowIds = () =>
    Array.from(
      screen.getByTestId("quiz-pick-list").querySelectorAll("[data-testid^='quiz-pick-']"),
    ).map(el => el.getAttribute("data-testid"));

  it("filters by concept name, case-insensitively", () => {
    mount();
    search("STACK");
    expect(rowIds()).toEqual(["quiz-pick-stack-frames"]);
  });

  it("clears on Escape", () => {
    mount();
    search("stack");
    fireEvent.keyDown(screen.getByTestId("quiz-topic-search"), { key: "Escape" });
    expect(screen.getByTestId("quiz-topic-search")).toHaveValue("");
  });

  it("matches a course code", () => {
    mount();
    search("cs101");
    expect(rowIds()).toEqual([
      "quiz-pick-tail-recursion",
      "quiz-pick-recursion",
      "quiz-pick-stack-frames",
      "quiz-pick-base-cases",
    ]);
  });

  it("finds the concept on the card too", () => {
    // Recursion is held back from the list while it is the proposal, but a
    // student who types its name expects to see it.
    mount();
    search("recursion");
    expect(rowIds()).toContain("quiz-pick-recursion");
  });

  it("says so when nothing matches, and restores the list when cleared", () => {
    mount();
    search("zzz");
    expect(screen.getByTestId("quiz-topic-search-empty")).toHaveTextContent("No concepts match “zzz”");
    search("");
    expect(screen.queryByTestId("quiz-topic-search-empty")).toBeNull();
  });
});

describe("QuizHome — narrowing the topic list to a course", () => {
  const rowIds = () =>
    Array.from(
      screen.getByTestId("quiz-pick-list").querySelectorAll("[data-testid^='quiz-pick-']"),
    ).map(el => el.getAttribute("data-testid"));

  it("offers All plus one pill per course, and a pill shows only that course", () => {
    mount();
    expect(screen.getByTestId("quiz-course-all")).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByTestId("quiz-course-c-math"));
    expect(screen.getByTestId("quiz-course-c-math")).toHaveAttribute("aria-pressed", "true");
    expect(rowIds()).toEqual(["quiz-pick-determinants", "quiz-pick-eigenvalues", "quiz-pick-matrices"]);
    // One course on screen: no heading restating the pill.
    expect(within(screen.getByTestId("quiz-pick-list")).queryByText(/MATH/)).toBeNull();

    fireEvent.click(screen.getByTestId("quiz-course-all"));
    expect(rowIds()).toHaveLength(6);
  });

  it("composes with the search", () => {
    mount();
    fireEvent.click(screen.getByTestId("quiz-course-c-cs"));
    fireEvent.change(screen.getByTestId("quiz-topic-search"), { target: { value: "re" } });
    // Both filters apply: CS101 concepts whose name contains "re".
    expect(rowIds()).toEqual(["quiz-pick-tail-recursion", "quiz-pick-recursion"]);
  });

  it("names the course when it has nothing else to offer", () => {
    const csOnlyOne = NODES.filter(n => n.course_id === "c-math" || n.id === "recursion");
    mount({ home: { nodes: csOnlyOne } });
    fireEvent.click(screen.getByTestId("quiz-course-c-cs"));
    // Recursion is the card, so CS101 has nothing left to list.
    expect(screen.getByTestId("quiz-topic-search-empty")).toHaveTextContent("Nothing else in CS101 yet");
  });

  it("draws no pills for a single course", () => {
    mount({ home: { nodes: NODES.filter(n => n.course_id === "c-cs") } });
    expect(screen.queryByTestId("quiz-course-all")).toBeNull();
  });
});

describe("QuizHome — the due set", () => {
  it("is a link under the card's actions, not a row in the topic list", () => {
    mount();
    const due = screen.getByTestId("quiz-review-due");
    expect(within(screen.getByTestId("quiz-proposal")).getByTestId("quiz-review-due")).toBe(due);
    expect(within(screen.getByTestId("quiz-pick-list")).queryByTestId("quiz-review-due")).toBeNull();
  });
});

describe("QuizHome — the live neighbourhood", () => {
  it("draws the card's concept with its neighbours, and a neighbour becomes the card", () => {
    mount();
    const graph = screen.getByTestId("quiz-neighbourhood");
    const ids = Array.from(graph.querySelectorAll("[data-testid='graph-node-item']")).map(li =>
      li.getAttribute("data-node-id"),
    );
    // Recursion's real neighbours, from EDGES.
    expect(ids).toEqual(expect.arrayContaining(["recursion", "base-cases", "stack-frames", "tail-recursion"]));

    const activate = (id: string) =>
      graph.querySelector(`[data-node-id='${id}'] [data-testid='graph-node-activate']`) as HTMLElement;
    // The centre already is the card.
    fireEvent.click(activate("recursion"));
    expect(screen.getByTestId("quiz-proposal-name")).toHaveTextContent("Recursion");
    expect(screen.queryByTestId("quiz-pick-reset")).toBeNull();

    fireEvent.click(activate("base-cases"));
    expect(screen.getByTestId("quiz-proposal-name")).toHaveTextContent("Base cases");
  });
});

describe("QuizHome — the adjust dialog", () => {
  it("marks the link active while open and writes the choices back on Done", () => {
    const { actions } = mount();

    const link = screen.getByTestId("quiz-adjust");
    expect(link).not.toHaveAttribute("data-active");

    fireEvent.click(link);
    expect(screen.getByTestId("quiz-adjust")).toHaveAttribute("data-active", "true");
    expect(actions.configure).toHaveBeenCalledWith(true);

    const dialog = screen.getByTestId("quiz-adjust-dialog");
    expect(dialog).toHaveTextContent("Recursion · CS101");
    fireEvent.click(within(dialog).getByTestId("quiz-seg-difficulty-fierce"));
    fireEvent.click(within(dialog).getByTestId("quiz-adjust-done"));

    expect(actions.setConfig).toHaveBeenCalledWith({
      count: 2,
      difficulty: "fierce",
      feedback: "at-end",
    });
    expect(actions.start).not.toHaveBeenCalled();
    expect(screen.queryByTestId("quiz-adjust-dialog")).toBeNull();
  });

  it("explains what the Answers choice changes", () => {
    mount();
    fireEvent.click(screen.getByTestId("quiz-adjust"));

    const dialog = screen.getByTestId("quiz-adjust-dialog");
    expect(dialog).toHaveTextContent("Answers stay hidden while you work");

    fireEvent.click(within(dialog).getByTestId("quiz-seg-feedback-as-you-go"));
    expect(dialog).toHaveTextContent("After each answer you'll see whether it was right");
  });

  it("starts with its own config", () => {
    const { actions } = mount();
    fireEvent.click(screen.getByTestId("quiz-adjust"));

    const dialog = screen.getByTestId("quiz-adjust-dialog");
    fireEvent.click(within(dialog).getByTestId("quiz-seg-count-4"));
    fireEvent.click(within(dialog).getByTestId("quiz-adjust-start"));

    expect(actions.start).toHaveBeenCalledWith(
      expect.objectContaining({ conceptId: "recursion" }),
      { count: 4, difficulty: "gentle", feedback: "at-end" },
    );
  });

  it("picks up settings that land after it was opened, instead of starting stale ones", () => {
    // Open Adjust before `GET /api/quiz/config` resolves and the `SET_CONFIG`
    // that follows moves `session.config` underneath the dialog. The draft used
    // to keep the pre-config values, so Start ran a quiz the card behind it had
    // already stopped describing.
    const home = buildHome();
    const actions = buildActions();
    const screenFor = (s: QuizSession) => (
      <QuizHome
        userId="u1"
        home={home}
        config={CONFIG}
        entry={entry()}
        session={s}
        actions={actions}
      />
    );
    const { rerender } = render(screenFor(session()));

    fireEvent.click(screen.getByTestId("quiz-adjust"));
    expect(screen.getByTestId("quiz-adjust-start")).toHaveTextContent("Start · 2 gentle");

    rerender(
      screenFor(session({ config: { count: 4, difficulty: "fierce", feedback: "at-end" } })),
    );
    expect(screen.getByTestId("quiz-adjust-start")).toHaveTextContent("Start · 4 fierce");

    fireEvent.click(screen.getByTestId("quiz-adjust-start"));
    expect(actions.start).toHaveBeenCalledWith(expect.objectContaining({ conceptId: "recursion" }), {
      count: 4,
      difficulty: "fierce",
      feedback: "at-end",
    });
  });

  it("keeps a choice made in the dialog when nothing outside it moved", () => {
    // The other half of the effect above: re-seeding must not fire on a plain
    // re-render, or the settings row would snap back while it is being used.
    const { actions, home, view } = mount();
    fireEvent.click(screen.getByTestId("quiz-adjust"));
    fireEvent.click(within(screen.getByTestId("quiz-adjust-dialog")).getByTestId("quiz-seg-count-4"));

    view.rerender(
      <QuizHome
        userId="u1"
        home={home}
        config={CONFIG}
        entry={entry()}
        session={session()}
        actions={actions}
      />,
    );
    expect(screen.getByTestId("quiz-adjust-start")).toHaveTextContent("Start · 4 gentle");
  });
});

describe("QuizHome — arrival", () => {
  it("makes a `?concept=` link the proposal, with its own reason", () => {
    const { actions } = mount({
      entry: entry({ concept: "matrices", source: { kind: "tree", conceptId: "matrices" } }),
    });

    const proposal = screen.getByTestId("quiz-proposal");
    expect(proposal).toHaveTextContent("Matrices");
    expect(proposal).toHaveTextContent("From your tree");

    fireEvent.click(screen.getByTestId("quiz-start"));
    expect(actions.start).toHaveBeenCalledWith(
      expect.objectContaining({ conceptId: "matrices", courseId: "c-math" }),
      SESSION_CONFIG,
    );
  });

  it("resolves a legacy `?topic=` name the same way", () => {
    // The other half of the deep-link path: `topic` is a concept NAME, matched
    // case-insensitively (the tree's and dashboard's old links).
    const { actions } = mount({
      entry: entry({ topic: "matrices", source: { kind: "link" } }),
    });

    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent("Matrices");
    expect(toast.info).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("quiz-start"));
    expect(actions.start).toHaveBeenCalledWith(
      expect.objectContaining({ conceptId: "matrices", courseId: "c-math" }),
      SESSION_CONFIG,
    );
  });

  it("says where a note's concept came from", () => {
    mount({
      entry: entry({ concept: "matrices", source: { kind: "notes", noteId: "n1" } }),
    });
    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent("From your note");
  });

  it("keeps the topic list beside a deep link when nothing is due", () => {
    // A deep link onto a tree with nothing left to review: the card stands,
    // nothing is due, and every other concept is still one click away.
    const mastered = NODES.map(n => ({ ...n, mastery_tier: "mastered" as const }));
    mount({
      home: { nodes: mastered },
      entry: entry({ concept: "matrices", source: { kind: "tree" } }),
    });

    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent("Matrices");
    expect(screen.queryByTestId("quiz-review-due")).toBeNull();
    const list = screen.getByTestId("quiz-pick-list");
    expect(within(list).queryByTestId("quiz-pick-matrices")).toBeNull();
    expect(within(list).getByTestId("quiz-pick-recursion")).toBeInTheDocument();
  });

  it("says so once when the link names something outside the semester", () => {
    const { view } = mount({
      entry: entry({ concept: "not-in-this-term", source: { kind: "link" } }),
    });

    expect(toast.info).toHaveBeenCalledTimes(1);
    expect(toast.info).toHaveBeenCalledWith("That concept isn't in your current semester");
    // …and the ordinary home renders underneath.
    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent("Recursion");

    view.rerender(
      <QuizHome
        userId="u1"
        home={buildHome()}
        config={CONFIG}
          entry={entry({ concept: "not-in-this-term", source: { kind: "link" } })}
        session={session()}
        actions={buildActions()}
      />,
    );
    expect(toast.info).toHaveBeenCalledTimes(1);
  });

  it("turns `?course=` into a course queue", () => {
    const { actions } = mount({
      entry: entry({ course: "c-cs", source: { kind: "tree", returnTo: "/tree" } }),
    });

    const proposal = screen.getByTestId("quiz-proposal");
    expect(proposal).toHaveTextContent("Practice CS101");
    expect(proposal).toHaveTextContent("4 concepts due");
    expect(proposal).toHaveTextContent(`${QUEUE_COUNT} questions each, gentle`);

    fireEvent.click(screen.getByTestId("quiz-start"));
    const [request, config] = (actions.start as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(request.scope).toEqual({
      kind: "course",
      courseId: "c-cs",
      queue: ["tail-recursion", "recursion", "stack-frames", "base-cases"],
    });
    expect(config.count).toBe(QUEUE_COUNT);
  });

  it("turns `?scope=due` into the due card", () => {
    const { actions } = mount({ entry: entry({ scope: "due", source: { kind: "dashboard" } }) });

    const proposal = screen.getByTestId("quiz-proposal");
    expect(proposal).toHaveTextContent("Review everything due");
    expect(proposal).toHaveTextContent("7 concepts across 2 courses · starting with the 5 weakest");
    // The card already is the due set, so the list does not offer it again.
    expect(screen.getByTestId("quiz-proposal-name")).toHaveTextContent("Review everything due");
    expect(screen.queryByTestId("quiz-review-due")).toBeNull();

    fireEvent.click(screen.getByTestId("quiz-start"));
    const [request] = (actions.start as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(request.intent).toBe("review");
    expect(request.scope.queue).toHaveLength(5);
  });
});

describe("QuizHome — the states with no proposal", () => {
  it("sends a student with no courses somewhere they can add one", () => {
    mount({ home: { nodes: [], courses: [], edges: [] } });

    const empty = screen.getByTestId("quiz-empty-state");
    expect(empty).toHaveTextContent("Add a course to start quizzing");
    expect(within(empty).getByRole("link")).toHaveAttribute("href", "/dashboard");
  });

  it("offers both ways to grow an empty tree", () => {
    mount({ home: { nodes: [], edges: [] } });

    const empty = screen.getByTestId("quiz-empty-state");
    expect(empty).toHaveTextContent("Your tree is empty");
    const hrefs = within(empty)
      .getAllByRole("link")
      .map(a => a.getAttribute("href"));
    expect(hrefs).toEqual(["/library", "/learn"]);
  });

  it("still offers the list when everything is mastered", () => {
    const mastered = NODES.map(n => ({ ...n, mastery_tier: "mastered" as const }));
    mount({ home: { nodes: mastered } });

    expect(screen.getByTestId("quiz-empty-state")).toHaveTextContent("Nothing needs review");
    // No card, so nothing is held back from the list.
    expect(
      within(screen.getByTestId("quiz-pick-list")).getByTestId("quiz-pick-recursion"),
    ).toBeInTheDocument();
  });

  it("offers a retry when the load failed", () => {
    const { home } = mount({
      home: {
        status: "error",
        error: { code: "NETWORK", message: "You look offline.", retryable: true },
      },
    });

    expect(screen.getByTestId("quiz-home-error")).toHaveTextContent("You look offline.");
    fireEvent.click(screen.getByTestId("quiz-home-retry"));
    expect(home.refresh).toHaveBeenCalled();
  });

  it("shows no options at all until `/config` lands", () => {
    mount({ config: null });
    fireEvent.click(screen.getByTestId("quiz-adjust"));

    const dialog = screen.getByTestId("quiz-adjust-dialog");
    expect(within(dialog).queryByTestId("quiz-seg-count")).toBeNull();
    expect(within(dialog).queryByTestId("quiz-seg-difficulty")).toBeNull();
    // The one list that is a client concept (R-2) is always there.
    expect(within(dialog).getByTestId("quiz-seg-feedback")).toBeInTheDocument();
  });
});
