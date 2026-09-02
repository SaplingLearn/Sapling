// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { markRadius } from "@/components/graph/ConceptNode";
import { __resetReducedMotionStoreForTests } from "@/lib/usePrefersReducedMotion";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import type { QuizItem, QuizSession, SubmitResult } from "@/lib/quiz/types";
import { QuizResults } from "./QuizResults";
import { buildMissedItems } from "./MissedList";

// B2 owns `question/AskPanel`; this screen only has to open it with the right
// seed. The mock renders the seed so the assertion is on the props, not on
// whatever the real sheet does with them.
vi.mock("../question/AskPanel", () => ({
  AskPanel: (props: { open: boolean; seed: Record<string, string>; conceptName: string }) =>
    props.open ? (
      <div data-testid="quiz-ask-panel" data-concept={props.conceptName}>
        {JSON.stringify(props.seed)}
      </div>
    ) : null,
}));

// The reduced-motion MEDIA query is forced off in this file so the
// `prefersReducedMotion` PROP is the only thing under test (the repo's vitest
// setup defaults the query to `matches: true`, which would mask it).
beforeEach(() => {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

afterEach(() => {
  cleanup();
  __resetReducedMotionStoreForTests();
  vi.restoreAllMocks();
});

const CONCEPT = {
  id: "recursion",
  name: "Recursion",
  courseCode: "CS101",
  color: "#7b4b99",
  tier: "struggling",
  mastery: 0.29,
};

const STEMS: Record<number, string> = {
  101: "What is a base case?",
  102: "What happens if a recursive function has no base case?",
  103: "Which call pattern is tail recursive?",
};

function item(id: number): QuizItem {
  return {
    index: id - 101,
    question: {
      id,
      question: STEMS[id],
      difficulty: "medium",
      options: [
        { label: "A", text: "It returns immediately" },
        { label: "B", text: "It recurses forever and overflows the stack" },
        { label: "C", text: "It is optimised away" },
        { label: "D", text: "Nothing at all" },
      ],
    },
    selectedIndex: 0,
    verdict: null,
    flagged: false,
  };
}

const RESULT: SubmitResult = {
  score: 2,
  total: 3,
  mastery_before: 0.29,
  mastery_after: 0.46,
  results: [
    { question_id: "101", selected: "B", correct: true, correct_answer: "B", explanation: "Yes." },
    {
      question_id: "102",
      selected: "A",
      correct: false,
      correct_answer: "B",
      explanation: "Without a base case the recursion never stops.",
    },
    { question_id: "103", selected: "C", correct: true, correct_answer: "C", explanation: "Right." },
  ],
};

function session(over: Partial<QuizSession> = {}): QuizSession {
  return {
    intent: "practice",
    scope: { kind: "concept", conceptId: "recursion" },
    source: { kind: "tree", conceptId: "recursion" },
    config: { count: 3, difficulty: "medium", feedback: "at-end" },
    conceptId: "recursion",
    courseId: "cs101",
    attemptId: "attempt-1",
    items: [item(101), item(102), item(103)],
    cursor: 2,
    queueIndex: 0,
    phase: "results",
    error: null,
    result: RESULT,
    xp: { before: 300, after: 330, streak: 12 },
    deliveredShort: false,
    sourceAttemptId: null,
    reserved: null,
    ...over,
  };
}

function actions(): QuizActions {
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

function renderResults(
  over: Partial<QuizSession> = {},
  opts: {
    prefersReducedMotion?: boolean;
    acts?: QuizActions;
    nextConcept?: { id: string; name: string } | null;
  } = {},
) {
  const acts = opts.acts ?? actions();
  const view = render(
    <QuizResults
      session={session(over)}
      actions={acts}
      concept={CONCEPT}
      neighbourhood={{
        siblings: [
          { id: "base-cases", name: "Base cases", mastery: 0.52, tier: "learning", strength: 0.9 },
        ],
      }}
      prefersReducedMotion={opts.prefersReducedMotion ?? true}
      nextConcept={opts.nextConcept}
    />,
  );
  return { ...view, acts };
}

/** The growth circle's drawn radius and its scale ratio — 1 once grown. */
function growthMark(container: HTMLElement) {
  const body = container.querySelector(".concept-node__body--growth")!;
  return {
    r: Number(body.getAttribute("r")),
    grow: Number(body.getAttribute("style")?.match(/--concept-grow:\s*([\d.]+)/)?.[1]),
  };
}

const PERFECT: Partial<QuizSession> = {
  result: {
    ...RESULT,
    score: 3,
    results: RESULT.results.map(r => ({ ...r, correct: true, selected: r.correct_answer })),
  },
};

describe("QuizResults", () => {
  it("shows the score, the mastery delta and the XP line", () => {
    renderResults();
    expect(screen.getByTestId("quiz-results-score")).toHaveTextContent("2 of 3 correct");
    // tierBefore is the wire tier off the concept; tierAfter is the ONE value
    // derived from a score (R-12).
    expect(screen.getByTestId("quiz-results-mastery")).toHaveTextContent(
      "29% → 46% · struggling → learning",
    );
    expect(screen.getByTestId("quiz-results-xp")).toHaveTextContent("+30 XP · 12-day streak");
  });

  it("omits the XP line entirely when the gamification read failed (R-9)", () => {
    renderResults({ xp: null });
    expect(screen.queryByTestId("quiz-results-xp")).toBeNull();
    expect(screen.getByTestId("quiz-results-score")).toBeInTheDocument();
  });

  it("names the growth in the canvas's accessible label", () => {
    renderResults();
    expect(screen.getByTestId("quiz-results-graph")).toHaveAttribute(
      "aria-label",
      "Recursion node grew from 29% to 46% mastery",
    );
  });

  it("says the node moved, not grew, when mastery went down", () => {
    renderResults({ result: { ...RESULT, mastery_after: 0.2 } });
    expect(screen.getByTestId("quiz-results-graph")).toHaveAttribute(
      "aria-label",
      "Recursion node moved from 29% to 20% mastery",
    );
  });

  it("lists only the wrong answers, joined to their stems", () => {
    renderResults();
    const list = screen.getByTestId("quiz-missed-list");
    expect(list).toHaveTextContent("One to look at");
    expect(screen.getByTestId("quiz-missed-102")).toHaveTextContent(STEMS[102]);
    expect(screen.getByTestId("quiz-missed-102")).toHaveTextContent(
      "You chose A · the answer is B",
    );
    expect(screen.queryByTestId("quiz-missed-101")).toBeNull();
    expect(screen.queryByTestId("quiz-missed-103")).toBeNull();
  });

  it("joins the string question_id off the wire to the numeric one on the item", () => {
    // The wire sends `str(q["id"])` while `WireQuestion.id` is a number — a
    // strict === would match nothing and render a stemless row.
    const missed = buildMissedItems(session());
    expect(missed).toHaveLength(1);
    expect(missed[0]).toMatchObject({
      questionId: "102",
      stem: STEMS[102],
      chosenLabel: "A",
      chosenText: "It returns immediately",
      correctLabel: "B",
      correctText: "It recurses forever and overflows the stack",
    });
  });

  it("toggles the explanation disclosure and reveals the text", () => {
    renderResults();
    const toggle = screen.getByTestId("quiz-missed-explain-102");
    // The panel is always in the DOM (so `aria-controls` resolves) and hidden
    // until asked for, so visibility — not presence — is the assertion.
    const panel = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(panel).toHaveTextContent("Without a base case the recursion never stops.");

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(panel).not.toBeVisible();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(panel).toBeVisible();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(panel).not.toBeVisible();
  });

  it("names the missed region from its eyebrow", () => {
    renderResults();
    const list = screen.getByTestId("quiz-missed-list");
    const heading = document.getElementById(list.getAttribute("aria-labelledby")!);
    expect(heading).toHaveTextContent("One to look at");
  });

  it("opens the AskPanel seeded from the row that asked", () => {
    renderResults();
    expect(screen.queryByTestId("quiz-ask-panel")).toBeNull();

    fireEvent.click(screen.getByTestId("quiz-missed-ask-102"));
    const panel = screen.getByTestId("quiz-ask-panel");
    expect(panel).toHaveAttribute("data-concept", "Recursion");
    expect(JSON.parse(panel.textContent ?? "{}")).toEqual({
      stem: STEMS[102],
      chosenLabel: "A",
      chosenText: "It returns immediately",
      correctLabel: "B",
      correctText: "It recurses forever and overflows the stack",
      explanation: "Without a base case the recursion never stops.",
    });
  });

  it("replaces the review section with the perfect-run line", () => {
    renderResults(PERFECT);
    expect(screen.getByTestId("quiz-results-perfect")).toHaveTextContent(
      "Nothing to review — every answer was right. Recursion keeps growing on your tree.",
    );
    expect(screen.queryByTestId("quiz-missed-list")).toBeNull();
    expect(screen.getByTestId("quiz-again")).toBeInTheDocument();
    expect(screen.queryByTestId("quiz-practise-missed")).toBeNull();
  });

  it("restarts the same concept on the session's own config", () => {
    const { acts } = renderResults(PERFECT);
    fireEvent.click(screen.getByTestId("quiz-again"));
    // No config override: `useQuizSession.start` defaults it to the live
    // session's config, so omitting it IS "the same quiz again" — passing
    // prefs here would silently change the length or difficulty.
    expect(acts.start).toHaveBeenCalledTimes(1);
    expect(acts.start).toHaveBeenCalledWith({
      intent: "practice",
      scope: { kind: "concept", conceptId: "recursion" },
      conceptId: "recursion",
      courseId: "cs101",
    });
  });

  it("offers the next concept while the queue has more, and calls nextInQueue", () => {
    const { acts } = renderResults({
      scope: { kind: "course", courseId: "cs101", queue: ["recursion", "base-cases"] },
      queueIndex: 0,
    });
    expect(screen.queryByTestId("quiz-practise-missed")).toBeNull();
    fireEvent.click(screen.getByTestId("quiz-next-concept"));
    expect(acts.nextInQueue).toHaveBeenCalledTimes(1);
  });

  it("names the next concept when the graph could resolve it", () => {
    renderResults(
      {
        scope: { kind: "course", courseId: "cs101", queue: ["recursion", "base-cases"] },
        queueIndex: 0,
      },
      { nextConcept: { id: "base-cases", name: "Base cases" } },
    );
    expect(screen.getByTestId("quiz-next-concept")).toHaveTextContent("Next: Base cases →");
  });

  it("still offers the queue exit unnamed when the next id can't be named", () => {
    // `nextConcept` is a LABEL: a next id outside the scoped graph must not
    // hide the exit, and must not get an invented name.
    renderResults(
      {
        scope: { kind: "due", queue: ["recursion", "off-graph"] },
        queueIndex: 0,
      },
      { nextConcept: null },
    );
    expect(screen.getByTestId("quiz-next-concept")).toHaveTextContent("Next concept →");
  });

  it("falls back to practising the missed questions, and calls practiseMissed", () => {
    const { acts } = renderResults();
    const button = screen.getByTestId("quiz-practise-missed");
    expect(button).toHaveTextContent("Practise the one you missed");
    fireEvent.click(button);
    expect(acts.practiseMissed).toHaveBeenCalledTimes(1);
  });

  it("says 'ones' — uncounted — when more than one was missed", () => {
    // The prototype's `practiseLabel`: never a count. The count is already the
    // eyebrow above the list.
    renderResults({
      result: {
        ...RESULT,
        score: 1,
        results: RESULT.results.map((r, i) => (i === 0 ? { ...r, correct: false } : r)),
      },
    });
    expect(screen.getByTestId("quiz-missed-list")).toHaveTextContent("2 to look at");
    expect(screen.getByTestId("quiz-practise-missed")).toHaveTextContent(
      "Practise the ones you missed",
    );
  });

  it("says so when an item was submitted unanswered", () => {
    // `selected` is "" on the wire for a skipped item; "You chose  · …" would
    // read as a rendering bug.
    const missed = buildMissedItems(
      session({
        result: {
          ...RESULT,
          results: RESULT.results.map((r, i) => (i === 1 ? { ...r, selected: "" } : r)),
        },
      }),
    );
    expect(missed[0]).toMatchObject({ chosenLabel: "", chosenText: "" });

    renderResults({
      result: {
        ...RESULT,
        results: RESULT.results.map((r, i) => (i === 1 ? { ...r, selected: "" } : r)),
      },
    });
    expect(screen.getByTestId("quiz-missed-102")).toHaveTextContent("No answer · the answer is B");
  });

  it("labels the secondary exit from the source and calls exit()", () => {
    const { acts } = renderResults({ source: { kind: "notes", noteId: "n1" } });
    const back = screen.getByTestId("quiz-back-to-source");
    expect(back).toHaveTextContent("Back to your note");
    fireEvent.click(back);
    expect(acts.exit).toHaveBeenCalledWith();
  });

  it("sends Done to quiz home", () => {
    const { acts } = renderResults();
    fireEvent.click(screen.getByTestId("quiz-done"));
    expect(acts.exit).toHaveBeenCalledWith("/quiz");
  });

  it("labels a review attempt as focused on what was missed (R-5)", () => {
    renderResults({
      intent: "review",
      scope: { kind: "missed", conceptId: "recursion", missedCount: 1 },
    });
    expect(screen.getByText("Focused on what you missed")).toBeInTheDocument();
  });

  it("says the questions were the same ones when the server re-served them all (G5)", () => {
    renderResults({
      intent: "review",
      scope: { kind: "missed", conceptId: "recursion", missedCount: 2 },
      reserved: { reservedCount: 2, regeneratedCount: 0 },
    });
    expect(screen.getByText("The ones you missed, again")).toBeInTheDocument();
  });

  it("keeps the R-5 wording when the practice quiz was partly regenerated", () => {
    renderResults({
      intent: "review",
      scope: { kind: "missed", conceptId: "recursion", missedCount: 3 },
      reserved: { reservedCount: 1, regeneratedCount: 2 },
    });
    expect(screen.getByText("Focused on what you missed")).toBeInTheDocument();
  });

  it("keeps the R-5 wording when the remainder failed and the quiz came back short", () => {
    // The server's degrade path: it recovered 2, the top-up generation 502'd,
    // and it served the 2 rather than deny practice already earned. That comes
    // back as regeneratedCount 0 on a quiz that is MISSING one of the items
    // being claimed, so "THE ones you missed" would overclaim.
    renderResults({
      intent: "review",
      scope: { kind: "missed", conceptId: "recursion", missedCount: 3 },
      reserved: { reservedCount: 2, regeneratedCount: 0 },
      deliveredShort: true,
    });
    expect(screen.getByText("Focused on what you missed")).toBeInTheDocument();
    expect(screen.queryByText("The ones you missed, again")).toBeNull();
  });

  it("keeps the R-5 wording when nothing could be re-served", () => {
    renderResults({
      intent: "review",
      scope: { kind: "missed", conceptId: "recursion", missedCount: 2 },
      reserved: { reservedCount: 0, regeneratedCount: 2 },
    });
    expect(screen.getByText("Focused on what you missed")).toBeInTheDocument();
  });

  it("never claims a re-serve outside a practise-missed scope", () => {
    // Defensive: `reserved` is only ever set by a generate that named a source
    // attempt, but the eyebrow is gated on the SCOPE and must stay that way —
    // an ordinary quiz labelled "the ones you missed" would be a lie.
    renderResults({ reserved: { reservedCount: 2, regeneratedCount: 0 } });
    expect(screen.queryByText("The ones you missed, again")).toBeNull();
    expect(screen.queryByText("Focused on what you missed")).toBeNull();
  });

  it("renders the grown node at its end state immediately under reduced motion", () => {
    const { container } = renderResults({}, { prefersReducedMotion: true });
    // The end state, first paint: the after-radius, at full scale — no
    // transition to run.
    const mark = growthMark(container);
    expect(mark.r).toBeCloseTo(markRadius(0.46, false, 2.5), 5);
    expect(mark.grow).toBe(1);
  });

  it("grows once and does not replay when the screen re-renders", async () => {
    // With motion on, the mark starts at the BEFORE ratio and grows to 1. The
    // headline behaviour of this screen is that it then stays there: a
    // disclosure toggle (or opening the AskPanel) must not restart it.
    const { container } = renderResults({}, { prefersReducedMotion: false });
    expect(growthMark(container).grow).toBeCloseTo(
      markRadius(0.29, false, 2.5) / markRadius(0.46, false, 2.5),
      3,
    );
    await waitFor(() => expect(growthMark(container).grow).toBe(1));

    fireEvent.click(screen.getByTestId("quiz-missed-explain-102"));
    expect(screen.getByTestId("quiz-missed-explain-102")).toHaveAttribute("aria-expanded", "true");

    const after = growthMark(container);
    expect(after.grow).toBe(1);
    expect(after.r).toBeCloseTo(markRadius(0.46, false, 2.5), 5);
  });
});
