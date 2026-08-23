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
 *   - the resume strip, its Resume, and its client-side Discard (R-3)
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
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";
import type { GraphEdge, GraphNode } from "@/lib/types";
import {
  alternativesOf,
  dueSet,
  groupByCourse,
  primaryOf,
  rankCandidates,
} from "@/lib/quiz/proposals";
import { DISMISSED_KEY, PREFS_KEY, QUEUE_COUNT } from "@/lib/quiz/session";
import type { EntryRequest } from "@/lib/quiz/source";
import type { QuizHome as QuizHomeData } from "@/lib/quiz/useQuizHome";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
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
    refresh: vi.fn(),
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
  const view = render(
    <QuizHome
      userId="u1"
      home={home}
      config={over.config === undefined ? CONFIG : over.config}
      entry={over.entry ?? entry()}
      session={over.session ?? session()}
      actions={actions}
    />,
  );
  return { home, actions, view };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
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

  it("falls back to the built sentence while the description is in flight", () => {
    mount({ home: { cardDescription: null } });

    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent(
      "CS101 · struggling · 3 connected concepts",
    );
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

  it("discards it client-side and reloads (R-3: there is no abandon endpoint)", () => {
    const { home } = mount({
      home: { resumable: { attempt: attemptDetail(), session: null, answered: 2 } },
    });

    fireEvent.click(screen.getByTestId("quiz-resume-discard"));

    expect(window.localStorage.getItem(DISMISSED_KEY)).toContain("attempt-1");
    expect(home.refresh).toHaveBeenCalled();
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

describe("QuizHome — the concept dialog", () => {
  it("opens off an alternative and starts with the config chosen in it", () => {
    const { actions } = mount();

    // The two alternatives are the next-weakest after the primary.
    fireEvent.click(screen.getByTestId("quiz-alternative-determinants"));

    const dialog = screen.getByTestId("quiz-concept-dialog");
    expect(dialog).toHaveTextContent("Determinants");

    // Every length offered is one `/config` named.
    const lengths = within(dialog).getByTestId("quiz-seg-count");
    expect(lengths).toHaveTextContent("2 questions");
    expect(lengths).toHaveTextContent("4 questions");
    expect(lengths).not.toHaveTextContent("5 questions");
    expect(lengths).not.toHaveTextContent("10 questions");

    fireEvent.click(within(dialog).getByTestId("quiz-seg-count-4"));
    fireEvent.click(within(dialog).getByTestId("quiz-seg-difficulty-fierce"));
    expect(within(dialog).getByTestId("quiz-concept-start")).toHaveTextContent("Start · 4 fierce");

    fireEvent.click(within(dialog).getByTestId("quiz-concept-start"));

    expect(actions.start).toHaveBeenCalledWith(
      {
        intent: "practice",
        scope: { kind: "concept", conceptId: "determinants" },
        conceptId: "determinants",
        courseId: "c-math",
      },
      { count: 4, difficulty: "fierce", feedback: "at-end" },
    );
    // Started from a dialog, so the choices are remembered (§5 B1.6).
    expect(window.localStorage.getItem(PREFS_KEY)).toContain("fierce");
  });

  it("opens off a pick-list row", () => {
    mount();
    fireEvent.click(screen.getByTestId("quiz-pick-open"));

    const list = screen.getByTestId("quiz-pick-list");
    expect(within(list).getByText("CS101 · Intro to Computer Science")).toBeInTheDocument();

    fireEvent.click(within(list).getByTestId("quiz-pick-base-cases"));
    expect(screen.getByTestId("quiz-concept-dialog")).toHaveTextContent("Base cases");
  });

  it("does not restate the meta line in the stand-in definition", () => {
    // The dialog's meta already opens with the course code and carries the
    // tier; the built sentence used to repeat both back (M6).
    mount();
    fireEvent.click(screen.getByTestId("quiz-pick-open"));
    fireEvent.click(within(screen.getByTestId("quiz-pick-list")).getByTestId("quiz-pick-base-cases"));

    const dialog = screen.getByTestId("quiz-concept-dialog");
    expect(dialog).toHaveTextContent("CS101 · 52% · learning");
    expect(dialog).toHaveTextContent("1 connected concept on your tree.");
    expect(dialog).not.toHaveTextContent("CS101 · learning · 1 connected concept");
  });

  it("collapses the pick list again", () => {
    mount();
    fireEvent.click(screen.getByTestId("quiz-pick-open"));
    fireEvent.click(screen.getByTestId("quiz-pick-back"));
    expect(screen.queryByTestId("quiz-pick-list")).toBeNull();
    expect(screen.getByTestId("quiz-proposal")).toBeInTheDocument();
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

  it("drops the 'Also worth a look' heading when there is nothing under it", () => {
    // A deep link onto a tree with nothing left to review: the card stands, but
    // there are no alternatives and nothing is due.
    const mastered = NODES.map(n => ({ ...n, mastery_tier: "mastered" as const }));
    mount({
      home: { nodes: mastered },
      entry: entry({ concept: "matrices", source: { kind: "tree" } }),
    });

    expect(screen.getByTestId("quiz-proposal")).toHaveTextContent("Matrices");
    expect(screen.queryByText("Also worth a look")).toBeNull();
    // …and the way out of the dead end is still there.
    expect(screen.getByTestId("quiz-pick-open")).toBeInTheDocument();
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
    fireEvent.click(screen.getByTestId("quiz-pick-open"));
    expect(screen.getByTestId("quiz-pick-list")).toBeInTheDocument();
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
