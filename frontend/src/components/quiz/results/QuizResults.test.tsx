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
  AskPanel: (props: {
    open: boolean;
    seed: Record<string, string>;
    conceptName: string;
    quizAsk?: { attemptId: string; questionIndex: number };
  }) =>
    props.open ? (
      <div
        data-testid="quiz-ask-panel"
        data-concept={props.conceptName}
        data-quiz-ask={props.quizAsk ? JSON.stringify(props.quizAsk) : ""}
      >
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
    prereq: null,
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
    cancel: vi.fn(),
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

/** The growth mark's drawn radius and its scale ratio — 1 once grown. The
 *  mark is a hand-drawn outline (a path), so the radius rides on `data-r`. */
function growthMark(container: HTMLElement) {
  const body = container.querySelector(".concept-node__body--growth")!;
  return {
    r: Number(body.getAttribute("data-r")),
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
  it("shows the learner model's block only when the submit reply carries one (A147)", () => {
    renderResults();
    expect(screen.queryByTestId("quiz-results-learning")).toBeNull();
    cleanup();
    renderResults({
      result: {
        ...RESULT,
        learning: {
          changes: [
            { concept_id: "recursion", concept_name: "Recursion", before: 0.29, after: 0.46, band_before: "novice", band_after: "develop" },
          ],
          review: { due_count: 0, next_due_at: null },
          next_step: "learn",
          learn: { concept_id: "recursion", concept_name: "Recursion", course_id: "cs101" },
        },
      },
    });
    // One measure: the quizzed concept's skill move leads; nothing else moved.
    expect(screen.getByTestId("quiz-results-mastery")).toHaveTextContent("Skill rose from 29% to 46% (now developing)");
    expect(screen.queryByTestId("quiz-results-change")).toBeNull();
    expect(screen.getByTestId("quiz-next-step-learn")).toHaveAttribute(
      "href",
      "/learn?topic=Recursion&concept=recursion&mode=socratic&course=cs101",
    );
    expect(screen.getByTestId("quiz-next-step-tree")).toHaveAttribute(
      "href",
      "/tree?node=recursion",
    );
  });

  it("names a level on one scale: with the learner model's block, the header is its skill meter (#866 K42)", () => {
    // The block says "still proficient" from 80%; the tier map says "learning"
    // up to 95%. One screen, one belief: the block's levels are the scale.
    renderResults({
      result: {
        ...RESULT,
        mastery_before: 0.82,
        mastery_after: 0.88,
        learning: {
          changes: [
            { concept_id: "recursion", concept_name: "Recursion", before: 0.82, after: 0.88, band_before: "profic", band_after: "profic" },
          ],
          review: { due_count: 0, next_due_at: null },
          next_step: "none",
          learn: null,
        },
      },
    });
    expect(screen.getByTestId("quiz-results-mastery")).toHaveTextContent(/^Skill rose from 82% to 88% \(still proficient\)$/);
    expect(screen.getByTestId("quiz-results-mastery")).not.toHaveTextContent(/learning|struggling|mastered/);
    expect(screen.queryByTestId("quiz-results-change")).toBeNull();
  });

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

  it("never says grew of a node that did not move, and says why when submit names it (#866 K40)", () => {
    // A submit writes evidence for a question at most once a day (A100) and
    // never for one its checks flagged: an all-right quiz can move nothing.
    renderResults({
      ...PERFECT,
      result: { ...PERFECT.result!, mastery_before: 0.4, mastery_after: 0.4, mastery_unmoved: ["not_verified", "already_counted"] },
    });
    expect(screen.getByTestId("quiz-results-graph")).toHaveAttribute("aria-label", "Recursion node stayed at 40% mastery");
    expect(screen.getByTestId("quiz-results-perfect")).toHaveTextContent(/^Nothing to review — every answer was right\.$/);
    expect(screen.getByTestId("quiz-results-unchanged")).toHaveTextContent(
      "Your mastery didn't change this time: a question that didn't pass its checks doesn't count; a question counts toward it once a day.",
    );
    // half a point is still the same whole percent on screen
    cleanup();
    renderResults({ result: { ...RESULT, mastery_before: 0.402, mastery_after: 0.404 } });
    expect(screen.getByTestId("quiz-results-graph")).toHaveAttribute("aria-label", "Recursion node stayed at 40% mastery");
  });

  it("states no reason for an unchanged percent submit names none for (#866 K40)", () => {
    // Evidence was written (a 99.5% mastery reads 100%; answers that net out):
    // "once a day" or "its checks" would be false.
    renderResults({ ...PERFECT, result: { ...PERFECT.result!, mastery_before: 0.996, mastery_after: 0.998 } });
    expect(screen.getByTestId("quiz-results-graph")).toHaveAttribute("aria-label", "Recursion node stayed at 100% mastery");
    expect(screen.queryByTestId("quiz-results-unchanged")).toBeNull();
  });

  it("names help and a failed write as what they are (#866 K40)", () => {
    renderResults({ result: { ...RESULT, mastery_before: 0.4, mastery_after: 0.4, mastery_unmoved: ["helped"] } });
    expect(screen.getByTestId("quiz-results-unchanged")).toHaveTextContent(
      "Your mastery didn't change this time: a right answer you had help with earns no credit.",
    );
    cleanup();
    renderResults({ result: { ...RESULT, mastery_before: 0.4, mastery_after: 0.4, mastery_unmoved: ["write_failed"] } });
    expect(screen.getByTestId("quiz-results-unchanged")).toHaveTextContent(
      "Your score is saved, but your mastery couldn't be updated this time.",
    );
  });

  it("says a round of the last quiz's missed questions was practice when it was all counted already (#866 K40)", () => {
    const missedRound = {
      scope: { kind: "missed", conceptId: "recursion", missedCount: 3 } as const,
      reserved: { reservedCount: 3, regeneratedCount: 0 },
    };
    renderResults({ ...missedRound, result: { ...RESULT, mastery_before: 0.4, mastery_after: 0.4, mastery_unmoved: ["already_counted"] } });
    expect(screen.getByTestId("quiz-results-unchanged")).toHaveTextContent(
      "These questions were in your last quiz, and a question counts toward your mastery once a day, so this round was practice.",
    );
    cleanup();
    // the same round with a flagged question too is not just practice
    renderResults({
      ...missedRound,
      result: { ...RESULT, mastery_before: 0.4, mastery_after: 0.4, mastery_unmoved: ["not_verified", "already_counted"] },
    });
    expect(screen.getByTestId("quiz-results-unchanged")).not.toHaveTextContent("this round was practice");
  });

  it("adds no note when the mastery moved, or when the learner model's block says it", () => {
    renderResults();
    expect(screen.queryByTestId("quiz-results-unchanged")).toBeNull();
    cleanup();
    renderResults({
      result: {
        ...RESULT,
        mastery_before: 0.4,
        mastery_after: 0.4,
        mastery_unmoved: ["already_counted"],
        learning: { changes: [], review: { due_count: 0, next_due_at: null }, next_step: "none", learn: null },
      },
    });
    expect(screen.queryByTestId("quiz-results-unchanged")).toBeNull();
    expect(screen.getByTestId("quiz-results-no-change")).toBeInTheDocument();
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
    // spec §13 A99: the panel names the row's question (attempt + index)
    expect(JSON.parse(panel.getAttribute("data-quiz-ask") || "null")).toEqual({
      attemptId: "attempt-1",
      questionIndex: 1, // question 102 is the attempt's second item
    });
    expect(JSON.parse(panel.textContent ?? "{}")).toEqual({
      stem: STEMS[102],
      chosenLabel: "A",
      chosenText: "It returns immediately",
      correctLabel: "B",
      correctText: "It recurses forever and overflows the stack",
      explanation: "Without a base case the recursion never stops.",
      written: false,
    });
  });

  it.each(["short_answer", "numeric", "symbolic"] as const)("shows the actual missed %s response and expected answer while preserving its tutor identity", (type) => {
    const written = item(102);
    written.question = { ...written.question, type, options: [] };
    const result = {
      ...RESULT,
      results: RESULT.results.map((row) => row.question_id === "102"
        ? { ...row, selected: "the submitted response", correct_answer: "the expected response" }
        : row),
    };
    renderResults({ items: [item(101), written, item(103)], result });
    const missed = screen.getByTestId("quiz-missed-102");
    expect(missed).toHaveTextContent("You wrote the submitted response · the answer is the expected response");
    expect(missed).not.toHaveTextContent("You chose Your answer");
    fireEvent.click(screen.getByTestId("quiz-missed-ask-102"));
    const panel = screen.getByTestId("quiz-ask-panel");
    expect(JSON.parse(panel.getAttribute("data-quiz-ask") || "null"))
      .toEqual({ attemptId: "attempt-1", questionIndex: 1 });
    expect(JSON.parse(panel.textContent ?? "{}"))
      .toMatchObject({ chosenText: "the submitted response", correctText: "the expected response" });
  });

  it("honestly labels an unanswered written item while still showing the expected answer", () => {
    const written = item(102);
    written.question = { ...written.question, type: "short_answer", options: [] };
    renderResults({ items: [item(101), written, item(103)], result: {
      ...RESULT,
      results: RESULT.results.map((row) => row.question_id === "102"
        ? { ...row, selected: "", correct_answer: "base case" } : row),
    } });
    expect(screen.getByTestId("quiz-missed-102")).toHaveTextContent("No answer · the answer is base case");
    fireEvent.click(screen.getByTestId("quiz-missed-ask-102"));
    expect(JSON.parse(screen.getByTestId("quiz-ask-panel").textContent ?? "{}"))
      .toMatchObject({ chosenLabel: "", chosenText: "", correctText: "base case" });
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
    expect(button).toHaveTextContent("Practice the one you missed");
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
      "Practice the ones you missed",
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

  it("reads a typed answer as what was written, never as placeholder labels", () => {
    // A numeric item: `selected` is the text the student typed and
    // `correct_answer` the expected text — there are no option letters.
    const numeric = (id: number): QuizItem => ({
      ...item(id),
      question: { ...item(id).question, type: "numeric", options: [] },
      selectedIndex: null,
    });
    const written = {
      items: [numeric(101), numeric(102), numeric(103)],
      result: {
        ...RESULT,
        results: [
          { question_id: "101", selected: "4", correct: false, correct_answer: "2", explanation: "Two." },
          { question_id: "102", selected: "", correct: false, correct_answer: "3", explanation: "Three." },
          { question_id: "103", selected: "4", correct: true, correct_answer: "4", explanation: "Four." },
        ],
      },
    };
    expect(buildMissedItems(session(written))[0]).toMatchObject({ written: true, chosenText: "4", correctText: "2" });

    renderResults(written);
    expect(screen.getByTestId("quiz-missed-101")).toHaveTextContent("You wrote 4 · the answer is 2");
    expect(screen.getByTestId("quiz-missed-102")).toHaveTextContent("No answer · the answer is 3");
    expect(screen.getByTestId("quiz-missed-list")).not.toHaveTextContent(/Your answer|Expected/);
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
