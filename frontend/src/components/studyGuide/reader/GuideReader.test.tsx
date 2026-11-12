// @vitest-environment jsdom
/**
 * The reader, through the screen, on the contract fixture: what it draws, the
 * Read / Skim toggle, read marks, each interactive block, the menu, the stale
 * banner and the tutor hand-off.
 *
 * Generation (the stream, polling, retry) is in GuideReader.generation.test.tsx;
 * the pure rules are in readerModel.test.ts and blocks/chartModel.test.ts.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const routerPush = vi.hoisted(() => vi.fn());

vi.mock("next/dynamic", async () => (await import("@/test-utils/mockNextDynamic")).mockNextDynamicModule());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: routerPush }) }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));

// The real renderer pulls in katex and highlight.js. This stand-in draws the
// text through the caller's paragraph renderer, which is where citations go.
vi.mock("@/components/chat/MarkdownChat", () => ({
  MarkdownChat: ({
    children,
    components,
  }: {
    children: string;
    components?: { p?: React.ComponentType<{ children: React.ReactNode }> };
  }) => {
    const P = components?.p ?? "p";
    return <P>{children}</P>;
  },
}));

vi.mock("@/lib/studyGuide/api", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/studyGuide/api")>()),
  getGuide: vi.fn(),
  patchGuide: vi.fn(),
  generateGuide: vi.fn(),
  regenerateBlock: vi.fn(),
  answerCheck: vi.fn(),
}));

vi.mock("@/components/quiz/question/askTurn", () => ({
  ABORTED: Symbol("aborted"),
  openTutorSession: vi.fn(),
  chatWithFallback: vi.fn(),
}));

import type React from "react";

import { chatWithFallback, openTutorSession } from "@/components/quiz/question/askTurn";
import { answerCheck, generateGuide, getGuide, patchGuide, regenerateBlock } from "@/lib/studyGuide/api";
import { BLOCK_TYPES, type AnswerResult, type Block, type GuideDetail, type GuideState } from "@/lib/studyGuide/types";

import { BLOCK_VIEWS } from "./blocks/BlockView";
import { deferred, fixtureGuide, renderReader } from "./readerTestKit";

const mocks = {
  getGuide: vi.mocked(getGuide),
  patchGuide: vi.mocked(patchGuide),
  generateGuide: vi.mocked(generateGuide),
  regenerateBlock: vi.mocked(regenerateBlock),
  answerCheck: vi.mocked(answerCheck),
  openTutorSession: vi.mocked(openTutorSession),
  chatWithFallback: vi.mocked(chatWithFallback),
};

const STATE: GuideState = { read_sections: ["s2"], saved_at: null, feedback: null };
const GUIDE_ID = "guide-fixture-1";

/** Render the reader on a guide and wait for it to load. */
async function open(guide: GuideDetail = fixtureGuide()) {
  mocks.getGuide.mockResolvedValue(guide);
  renderReader();
  await screen.findByTestId("guide-title");
  return userEvent.setup();
}

const block = (id: string) => screen.getByTestId(`guide-block-${id}`);
const answer = (over: Partial<AnswerResult>): AnswerResult => ({
  correct: false,
  correct_id: "b",
  explanation: "Count the values of i that pass the test.",
  counted: true,
  mastery: null,
  ...over,
});

beforeEach(() => {
  vi.resetAllMocks();
  mocks.patchGuide.mockResolvedValue(STATE);
});
afterEach(cleanup);

describe("the contract", () => {
  it("has a fixture whose items are prose and exactly the block types", () => {
    const types = new Set(fixtureGuide().content.sections.flatMap(section => section.items.map(item => item.type)));
    expect([...types].sort()).toEqual(["prose", ...BLOCK_TYPES].sort());
  });

  it("has a view for every block type and no other", () => {
    expect(Object.keys(BLOCK_VIEWS).sort()).toEqual([...BLOCK_TYPES].sort());
  });
});

describe("what the reader draws", () => {
  it("is titled Study, with the way back to the Study Guides home", async () => {
    await open();
    expect(screen.getByRole("heading", { level: 1, name: "Study" })).toBeInTheDocument();
    const back = screen.getByTestId("back-link");
    expect(back).toHaveAttribute("href", "/study/guide");
    expect(back).toHaveAccessibleName("Back to Study Guides");
  });

  it("has one page heading, with the guide's title under it and the sections under that", async () => {
    await open();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 2, name: "Control flow and functions" })).toBe(screen.getByTestId("guide-title"));
    const sections = screen.getAllByRole("heading", { level: 3 }).map(heading => heading.textContent);
    expect(sections).toEqual(["Loops", "Functions", "Scope", "Variables"]);
  });

  it("renders every item of the fixture: each prose passage and each block type", async () => {
    await open();
    const items = fixtureGuide().content.sections.flatMap(section => section.items);
    for (const item of items) {
      const testid = item.type === "prose" ? `guide-prose-${item.id}` : `guide-block-${item.id}`;
      expect(screen.getByTestId(testid)).toBeInTheDocument();
    }
    expect(items.filter(item => item.type !== "prose")).toHaveLength(BLOCK_TYPES.length);
  });

  it("shows the header: title, deck, labels, the countdown and the source count", async () => {
    await open();
    const guide = fixtureGuide();
    expect(screen.getByTestId("guide-title")).toHaveTextContent(guide.content.title);
    expect(screen.getByText(guide.content.deck)).toBeInTheDocument();
    expect(screen.getByText("AI generated")).toBeInTheDocument();
    expect(screen.getByText("Exam prep")).toBeInTheDocument();
    expect(screen.getByText("Standard")).toBeInTheDocument();
    expect(screen.getByText("Midterm Exam in 6 days")).toBeInTheDocument();
    expect(screen.getByText("3 sources · about 12 min")).toBeInTheDocument();
    expect(within(screen.getByTestId("guide-space-bar")).getByText("Loops · Struggling")).toBeInTheDocument();
    for (const takeaway of guide.content.takeaways) expect(screen.getByText(takeaway)).toBeInTheDocument();
  });

  it("leaves the countdown out once the due date has passed", async () => {
    await open(fixtureGuide({ due_date: "2026-03-01" }));
    expect(screen.queryByText(/Midterm Exam in/)).not.toBeInTheDocument();
    expect(screen.queryByText(/days? left/)).not.toBeInTheDocument();
  });

  it("numbers the sections and lists the sources", async () => {
    await open();
    expect(within(screen.getByTestId("guide-section-s1")).getByText("01")).toBeInTheDocument();
    expect(within(screen.getByTestId("guide-section-s4")).getByText("04")).toBeInTheDocument();
    const sources = screen.getByTestId("guide-sources");
    // Two documents and the quiz history, which is a source but not a material.
    expect(within(sources).getByText("Made from 2 of your materials and your quiz history")).toBeInTheDocument();
    for (const source of fixtureGuide().content.sources) {
      expect(within(sources).getByText(source.name)).toBeInTheDocument();
    }
  });

  it("cites a paragraph's source by name, linked to the sources list", async () => {
    await open();
    const cite = within(screen.getByTestId("guide-prose-s1-i1")).getByRole("link", { name: "Source: Lecture 3 slides.pdf" });
    expect(cite).toHaveAttribute("href", "#guide-sources");
    expect(screen.getByTestId("guide-sources")).toHaveAttribute("id", "guide-sources");
  });

  it("shows a queued section as queued, with nothing to mark read", async () => {
    await open();
    const queued = screen.getByTestId("guide-section-s3");
    expect(within(queued).getByText("Queued")).toBeInTheDocument();
    expect(screen.getByTestId("guide-section-read-s3")).toBeDisabled();
  });

  it("says so when the guide cannot be loaded", async () => {
    mocks.getGuide.mockRejectedValue(new Error('{"detail":"Guide not found."}'));
    renderReader();
    expect(await screen.findByTestId("guide-load-error")).toHaveTextContent("Guide not found.");
  });
});

describe("Read and Skim", () => {
  it("swaps each passage for its summary and keeps the blocks", async () => {
    const user = await open();
    expect(screen.getByTestId("guide-mode-read")).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByTestId("guide-mode-skim"));

    expect(screen.queryByTestId("guide-prose-s1-i1")).not.toBeInTheDocument();
    expect(screen.getByTestId("guide-skim-s1-i1")).toHaveTextContent(
      "A while loop repeats while its condition holds. Count the passes.",
    );
    expect(block("s1-i2")).toBeInTheDocument();
    expect(block("s2-i2")).toBeInTheDocument();
    // A passage with no summary is hidden in Skim.
    expect(screen.queryByTestId("guide-prose-s4-i1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("guide-skim-s4-i1")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("guide-mode-read"));
    expect(screen.getByTestId("guide-prose-s1-i1")).toBeInTheDocument();
  });
});

describe("read marks", () => {
  it("updates the ring at once and saves the new list", async () => {
    const user = await open();
    const progress = screen.getByTestId("guide-progress");
    expect(progress).toHaveTextContent("1 of 4 sections read");
    expect(screen.getByTestId("guide-section-read-s2")).toHaveTextContent("Read");

    await user.click(screen.getByTestId("guide-section-read-s1"));

    expect(progress).toHaveTextContent("2 of 4 sections read");
    expect(screen.getByTestId("guide-section-read-s1")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("guide-outline-read-s1")).toHaveAttribute("aria-pressed", "true");
    expect(mocks.patchGuide).toHaveBeenCalledWith("u1", GUIDE_ID, { read_sections: ["s2", "s1"] });
  });

  it("unmarks from the outline", async () => {
    const user = await open();
    await user.click(screen.getByTestId("guide-outline-read-s2"));
    expect(screen.getByTestId("guide-progress")).toHaveTextContent("0 of 4 sections read");
    expect(mocks.patchGuide).toHaveBeenCalledWith("u1", GUIDE_ID, { read_sections: [] });
  });

  it("rolls back and says so when the save fails", async () => {
    mocks.patchGuide.mockRejectedValue(new Error("offline"));
    const user = await open();
    await user.click(screen.getByTestId("guide-section-read-s1"));
    expect(await screen.findByText("That could not be saved. Try again.")).toBeInTheDocument();
    expect(screen.getByTestId("guide-progress")).toHaveTextContent("1 of 4 sections read");
    expect(screen.getByTestId("guide-section-read-s1")).toHaveAttribute("aria-pressed", "false");
  });

  it("calls the guide finished once every section is read", async () => {
    await open(fixtureGuide({ read_sections: ["s1", "s2", "s3", "s4"] }));
    expect(screen.getByTestId("guide-progress")).toHaveTextContent("Guide finished");
    expect(screen.getByTestId("guide-progress")).toHaveTextContent("Midterm Exam · Tue, Mar 17");
    expect(screen.getByTestId("guide-progress")).toHaveTextContent("6 days left");
  });
});

describe("the outline", () => {
  it("links each section and shows its live mastery", async () => {
    await open(fixtureGuide({ mastery: { Loops: "learning", Functions: "learning", Variables: "mastered" } }));
    const loops = screen.getByTestId("guide-outline-s1");
    expect(loops).toHaveAttribute("href", "#guide-section-s1");
    // Written when the student was struggling; they have moved on since.
    expect(loops).toHaveTextContent("Learning");
    expect(screen.getByTestId("guide-outline-s4")).toHaveTextContent("Mastered, one line");
    expect(screen.getByTestId("guide-section-s1")).toHaveAttribute("id", "guide-section-s1");
  });
});

describe("the mastered section", () => {
  it("opens as one line and expands to the full section", async () => {
    const user = await open();
    const section = screen.getByTestId("guide-section-s4");
    expect(within(section).getByText("You have mastered this, so it gets one line.")).toBeInTheDocument();
    expect(within(section).getByText("A variable is a name bound to a value.")).toBeInTheDocument();
    expect(screen.getByTestId("guide-prose-s4-i1")).not.toBeVisible();

    const expand = screen.getByTestId("guide-section-expand-s4");
    expect(expand).toHaveTextContent("Show full section");
    await user.click(expand);

    expect(screen.getByTestId("guide-prose-s4-i1")).toBeVisible();
    expect(expand).toHaveTextContent("Hide full section");
    expect(expand).toHaveAttribute("aria-expanded", "true");
  });
});

describe("the chart block", () => {
  it("names the drawing with its alt text and labels an illustrative chart", async () => {
    await open();
    const chart = block("s1-i2");
    expect(
      within(chart).getByRole("img", { name: "A straight line for one loop and a steeper curve for a nested loop." }),
    ).toBeInTheDocument();
    expect(within(chart).getByText("Illustrative shape, not plotted from data")).toBeInTheDocument();
    expect(within(chart).getByRole("link", { name: "Lecture 3 slides.pdf" })).toHaveAttribute("href", "#guide-sources");
    expect(within(chart).getByText("One loop")).toBeInTheDocument();
    // An illustrative chart has no axis numbers.
    expect(within(chart).queryByText("100")).not.toBeInTheDocument();
  });

  it("switches between Before and After", async () => {
    const user = await open();
    const chart = block("s1-i2");
    expect(screen.getByTestId("guide-chart-state-s1-i2-after")).toHaveTextContent("Nested");
    expect(within(chart).getByText("n to n squared")).toBeInTheDocument();
    expect(within(chart).getByText("Grows faster")).toBeInTheDocument();
    expect(chart.querySelectorAll("svg[role=img] path")).toHaveLength(2);

    await user.click(screen.getByTestId("guide-chart-state-s1-i2-before"));

    expect(within(chart).getByText("Starting point")).toBeInTheDocument();
    expect(within(chart).queryByText("n to n squared")).not.toBeInTheDocument();
    expect(chart.querySelectorAll("svg[role=img] path")).toHaveLength(1);
  });

  it("has no toggle when nothing is made for After, and numbers a chart plotted from data", async () => {
    const guide = fixtureGuide();
    const chart = guide.content.sections[0].items[1] as Extract<Block, { type: "chart" }>;
    chart.series = [chart.series[0]];
    chart.markers = [];
    chart.illustrative = false;
    await open(guide);
    expect(screen.queryByTestId("guide-chart-state-s1-i2")).not.toBeInTheDocument();
    expect(within(block("s1-i2")).queryByText(/Illustrative shape/)).not.toBeInTheDocument();
    expect(within(block("s1-i2")).getAllByText("10").length).toBeGreaterThan(0);
  });
});

describe("the worked example", () => {
  it("reveals one step at a time and starts over", async () => {
    const user = await open();
    const example = block("s1-i5");
    const first = within(example).getByText("List the values");
    const second = within(example).getByText("Count them");
    expect(first).not.toBeVisible();
    expect(within(example).getByText("0 of 2 steps")).toBeInTheDocument();

    const next = screen.getByTestId("guide-step-next-s1-i5");
    expect(next).toHaveTextContent("Show first step");
    expect(screen.queryByTestId("guide-step-reset-s1-i5")).not.toBeInTheDocument();
    await user.click(next);

    expect(first).toBeVisible();
    expect(second).not.toBeVisible();
    expect(within(example).getByText("1 of 2 steps")).toBeInTheDocument();
    expect(next).toHaveTextContent("Show next step");
    await user.click(next);

    expect(second).toBeVisible();
    expect(screen.queryByTestId("guide-step-next-s1-i5")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("guide-step-reset-s1-i5"));
    expect(first).not.toBeVisible();
    expect(within(example).getByText("0 of 2 steps")).toBeInTheDocument();
  });
});

describe("the other blocks", () => {
  it("shows mistakes with their fix and evidence", async () => {
    await open();
    const mistakes = block("s1-i3");
    expect(within(mistakes).getByText("Counting one pass too many")).toBeInTheDocument();
    expect(within(mistakes).getByText("From your quizzes on Loops.")).toBeInTheDocument();
  });

  it("gives the formula as display math, with its spoken form", async () => {
    await open();
    const formula = block("s1-i4");
    expect(within(formula).getByText(/^\$\$\s+\\text\{passes\}/)).toBeInTheDocument();
    expect(within(formula).getByText("Passes equal stop minus start, divided by step.")).toBeInTheDocument();
  });

  it("tags the most tested row of a comparison", async () => {
    await open();
    const table = within(block("s1-i6")).getByRole("table");
    expect(within(table).getAllByRole("columnheader").map(th => th.textContent)).toEqual(["While", "For"]);
    const tested = within(table).getByRole("rowheader", { name: /Common bug/ });
    expect(tested).toHaveTextContent("Most tested");
    expect(within(table).getByRole("rowheader", { name: /Use it when/ })).not.toHaveTextContent("Most tested");
  });

  it("lists key terms with their definitions", async () => {
    await open();
    const terms = block("s2-i2");
    expect(within(terms).getByText("Parameter")).toBeInTheDocument();
    expect(within(terms).getByText("What the function hands back to its caller.")).toBeInTheDocument();
  });
});

describe("the check block", () => {
  it("shows the nudge for a wrong pick and lets the student pick again", async () => {
    mocks.answerCheck.mockResolvedValueOnce(answer({ correct: false })).mockResolvedValueOnce(
      answer({
        correct: true,
        explanation: "0, 2, 4 and 6 pass the test.",
        counted: false,
        mastery: { concept: "Loops", before: "struggling", after: "learning" },
      }),
    );
    const user = await open();
    expect(within(block("s1-i8")).getByText("Counts toward mastery")).toBeInTheDocument();
    expect(screen.queryByTestId("guide-check-result-s1-i8")).not.toBeInTheDocument();
    expect(screen.queryByTestId("guide-block-regenerate-s1-i8")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("guide-check-option-s1-i8-a"));

    expect(mocks.answerCheck).toHaveBeenCalledWith("u1", GUIDE_ID, "s1-i8", "a");
    const result = await screen.findByTestId("guide-check-result-s1-i8");
    expect(result).toHaveTextContent("Not quite. Count the values of i that pass the test.");
    expect(screen.getByTestId("guide-check-option-s1-i8-a")).toHaveAccessibleName(/your answer, incorrect/);

    await user.click(screen.getByTestId("guide-check-option-s1-i8-b"));

    await waitFor(() => expect(screen.getByTestId("guide-check-result-s1-i8")).toHaveTextContent("Correct."));
    expect(screen.getByTestId("guide-check-result-s1-i8")).toHaveTextContent("0, 2, 4 and 6 pass the test.");
    expect(screen.getByTestId("guide-check-result-s1-i8")).toHaveTextContent("Loops: Struggling to Learning");
    expect(screen.getByTestId("guide-check-option-s1-i8-b")).toHaveAccessibleName(/correct answer/);
    // Mastery moved everywhere the guide shows it.
    expect(screen.getByTestId("guide-outline-s1")).toHaveTextContent("Learning");
    expect(screen.getByTestId("guide-concept-s1-i7-1")).toHaveTextContent("Learning");
  });

  it("leaves mastery out of the result when the tier did not change", async () => {
    mocks.answerCheck.mockResolvedValue(
      answer({ correct: true, mastery: { concept: "Loops", before: "struggling", after: "struggling" } }),
    );
    const user = await open();
    await user.click(screen.getByTestId("guide-check-option-s1-i8-b"));
    const result = await screen.findByTestId("guide-check-result-s1-i8");
    expect(result).toHaveTextContent("Correct.");
    expect(result).not.toHaveTextContent("Struggling to");
  });

  it("restores a stored answer when the guide loads", async () => {
    const guide = fixtureGuide({ answers: { "s1-i8": { option_id: "b", correct: true } } });
    const check = guide.content.sections[0].items[7] as Extract<Block, { type: "check" }>;
    check.correct_id = "b";
    check.explain_correct = "0, 2, 4 and 6 pass the test.";
    await open(guide);
    expect(screen.getByTestId("guide-check-result-s1-i8")).toHaveTextContent("Correct. 0, 2, 4 and 6 pass the test.");
    expect(screen.getByTestId("guide-check-option-s1-i8-b")).toHaveAccessibleName(/correct answer/);
    expect(mocks.answerCheck).not.toHaveBeenCalled();
  });

  it("says so when the answer cannot be checked", async () => {
    mocks.answerCheck.mockRejectedValue(new Error("offline"));
    const user = await open();
    await user.click(screen.getByTestId("guide-check-option-s1-i8-a"));
    expect(await screen.findByText("Your answer could not be checked. Try again.")).toBeInTheDocument();
    expect(screen.queryByTestId("guide-check-result-s1-i8")).not.toBeInTheDocument();
  });
});

describe("the concept map and the tutor", () => {
  it("shows each concept's live mastery, and Not Started for one the tree lacks", async () => {
    await open(fixtureGuide({ mastery: { Loops: "struggling", Variables: "mastered" } }));
    expect(screen.getByTestId("guide-concept-s1-i7-0")).toHaveTextContent("FoundationsVariablesMastered");
    expect(screen.getByTestId("guide-concept-s1-i7-1")).toHaveTextContent("Struggling");
    expect(screen.getByTestId("guide-concept-s1-i7-2")).toHaveTextContent("Not Started");
  });

  it("opens the tutor on the selected concept with the chosen prompt", async () => {
    mocks.openTutorSession.mockResolvedValue("sid-1");
    mocks.chatWithFallback.mockResolvedValue("Sure.");
    const user = await open();
    expect(screen.queryByTestId("guide-concept-prompt-s1-i7-0")).not.toBeInTheDocument();
    expect(within(block("s1-i7")).getByRole("link", { name: "Open in Tree" })).toHaveAttribute("href", "/tree");

    await user.click(screen.getByTestId("guide-concept-s1-i7-1"));

    expect(within(block("s1-i7")).getByText("Ask the tutor about Loops")).toBeInTheDocument();
    expect(within(block("s1-i7")).getByRole("link", { name: "Open in Tree" })).toHaveAttribute("href", "/tree?suggest=Loops");
    expect(screen.getByTestId("guide-concept-prompt-s1-i7-0")).toHaveTextContent("Explain it a simpler way");
    expect(screen.getByTestId("guide-concept-prompt-s1-i7-1")).toHaveTextContent("Give me another example");
    expect(screen.getByTestId("guide-concept-prompt-s1-i7-2")).toHaveTextContent("Quiz me on this");

    await user.click(screen.getByTestId("guide-concept-prompt-s1-i7-2"));

    await waitFor(() => expect(routerPush).toHaveBeenCalledWith("/learn?resume=sid-1"));
    expect(mocks.openTutorSession).toHaveBeenCalledWith("u1", "Loops", "course-cs101", expect.any(AbortSignal));
    expect(mocks.chatWithFallback.mock.calls[0][0]).toMatchObject({ sid: "sid-1", userId: "u1", message: "Quiz me on Loops." });
  });

  it("closes the prompts", async () => {
    const user = await open();
    await user.click(screen.getByTestId("guide-concept-s1-i7-0"));
    await user.click(screen.getByTestId("guide-concept-close-s1-i7"));
    expect(screen.queryByTestId("guide-concept-prompt-s1-i7-0")).not.toBeInTheDocument();
    expect(screen.getByTestId("guide-concept-s1-i7-0")).toHaveAttribute("aria-pressed", "false");
  });

  it("sends a question about the guide with its outline, then opens the tutor", async () => {
    mocks.openTutorSession.mockResolvedValue("sid-2");
    mocks.chatWithFallback.mockResolvedValue("Because the test fails.");
    const user = await open();
    expect(screen.getByTestId("guide-ask-send")).toBeDisabled();

    await user.type(screen.getByTestId("guide-ask-input"), "Why does a loop stop?");
    await user.click(screen.getByTestId("guide-ask-send"));

    await waitFor(() => expect(routerPush).toHaveBeenCalledWith("/learn?resume=sid-2"));
    expect(mocks.openTutorSession).toHaveBeenCalledWith(
      "u1",
      "Control flow and functions",
      "course-cs101",
      expect.any(AbortSignal),
    );
    const { message } = mocks.chatWithFallback.mock.calls[0][0];
    expect(message).toContain("My question: Why does a loop stop?");
    expect(message).toContain("2. Functions: A function names a block of code so it can be reused.");
  });

  it("stays on the guide and says so when the tutor cannot be opened", async () => {
    mocks.openTutorSession.mockRejectedValue(new Error("down"));
    const user = await open();
    await user.type(screen.getByTestId("guide-ask-input"), "Why?");
    await user.click(screen.getByTestId("guide-ask-send"));
    expect(await screen.findByText("The tutor could not be opened. Try again.")).toBeInTheDocument();
    expect(routerPush).not.toHaveBeenCalled();
  });
});

describe("regenerating one block", () => {
  it("shows the skeleton in place, then replaces only that block", async () => {
    const rewrite = deferred<{ block: Block }>();
    mocks.regenerateBlock.mockReturnValue(rewrite.promise);
    const user = await open();

    await user.click(screen.getByTestId("guide-block-regenerate-s2-i2"));

    expect(mocks.regenerateBlock).toHaveBeenCalledWith("u1", GUIDE_ID, "s2-i2");
    expect(
      within(block("s2-i2")).getByText("Regenerating this block. The rest of the guide stays as it is."),
    ).toBeInTheDocument();
    expect(within(block("s2-i2")).queryByText("Parameter")).not.toBeInTheDocument();
    expect(within(block("s1-i6")).getByText("While and for")).toBeInTheDocument();

    rewrite.resolve({
      block: {
        type: "key_terms",
        id: "s2-i2",
        title: "Rewritten terms",
        terms: [
          { term: "Argument", definition: "The value passed for a parameter." },
          { term: "Call", definition: "Running a function by name." },
        ],
      },
    });

    expect(await within(block("s2-i2")).findByText("Rewritten terms")).toBeInTheDocument();
    expect(within(block("s2-i2")).getByText("Argument")).toBeInTheDocument();
    expect(within(block("s2-i2")).queryByText("Parameter")).not.toBeInTheDocument();
    expect(screen.getByTestId("guide-prose-s2-i1")).toHaveTextContent("A **function** takes inputs");
    expect(within(block("s1-i6")).getByText("While and for")).toBeInTheDocument();
  });

  it("keeps the block and says so when it fails", async () => {
    mocks.regenerateBlock.mockRejectedValue(new Error("busy"));
    const user = await open();
    await user.click(screen.getByTestId("guide-block-regenerate-s2-i2"));
    expect(await screen.findByText("This block could not be regenerated. Try again.")).toBeInTheDocument();
    expect(within(block("s2-i2")).getByText("Parameter")).toBeInTheDocument();
  });
});

describe("the menu", () => {
  it("saves to the Library, then shows the saved state with a link there", async () => {
    mocks.patchGuide.mockResolvedValue({ ...STATE, saved_at: "2026-03-11T09:00:00+00:00" });
    const user = await open();
    expect(screen.queryByTestId("guide-menu-save")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("guide-menu"));
    await user.click(screen.getByTestId("guide-menu-save"));

    const saved = await screen.findByTestId("guide-menu-saved");
    expect(mocks.patchGuide).toHaveBeenCalledWith("u1", GUIDE_ID, { saved: true });
    expect(saved).toHaveTextContent("Saved to Library");
    expect(saved).toHaveTextContent("Open it there");
    expect(saved).toHaveAttribute("href", "/library");
    expect(screen.queryByTestId("guide-menu-save")).not.toBeInTheDocument();
  });

  it("opens on the saved state for a guide already in the Library", async () => {
    const user = await open(fixtureGuide({ saved_at: "2026-03-10T15:05:00+00:00" }));
    await user.click(screen.getByTestId("guide-menu"));
    expect(screen.getByTestId("guide-menu-saved")).toBeInTheDocument();
  });

  it("exports through the browser's print dialog and closes", async () => {
    const print = vi.fn();
    vi.stubGlobal("print", print);
    const user = await open();
    await user.click(screen.getByTestId("guide-menu"));
    await user.click(screen.getByTestId("guide-menu-export"));
    expect(print).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("guide-menu-export")).not.toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("closes on Escape", async () => {
    const user = await open();
    await user.click(screen.getByTestId("guide-menu"));
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("guide-menu-export")).not.toBeInTheDocument();
    expect(screen.getByTestId("guide-menu")).toHaveAttribute("aria-expanded", "false");
  });
});

describe("new lectures", () => {
  it("shows how many arrived, and Update starts an update generation", async () => {
    const run = deferred<GuideDetail>();
    mocks.generateGuide.mockReturnValue(run.promise);
    const user = await open();
    const stale = screen.getByTestId("guide-stale");
    expect(stale).toHaveTextContent("2 new lectures since this guide was made");
    expect(stale).toHaveTextContent("Updating keeps your edits and adds what changed.");
    expect(mocks.generateGuide).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("guide-update"));

    await waitFor(() =>
      expect(mocks.generateGuide).toHaveBeenCalledWith("u1", GUIDE_ID, "update", expect.any(Object)),
    );
    expect(await screen.findByTestId("guide-generating")).toBeInTheDocument();

    run.resolve(fixtureGuide({ new_materials: 0 }));

    expect(await screen.findByTestId("guide-updated")).toHaveTextContent("Guide is up to date");
    expect(screen.queryByTestId("guide-stale")).not.toBeInTheDocument();
    expect(screen.queryByTestId("guide-generating")).not.toBeInTheDocument();
  });

  it("has no banner for a guide with nothing new", async () => {
    await open(fixtureGuide({ new_materials: 0 }));
    expect(screen.queryByTestId("guide-stale")).not.toBeInTheDocument();
    expect(screen.queryByTestId("guide-updated")).not.toBeInTheDocument();
  });
});

describe("feedback", () => {
  it("saves the answer and thanks the student", async () => {
    const user = await open();
    expect(screen.getByText("Was this guide useful?")).toBeInTheDocument();
    await user.click(screen.getByTestId("guide-feedback-no"));
    expect(screen.getByText("Thanks, that shapes your next guide.")).toBeInTheDocument();
    expect(screen.getByTestId("guide-feedback-no")).toHaveAttribute("aria-pressed", "true");
    expect(mocks.patchGuide).toHaveBeenCalledWith("u1", GUIDE_ID, { feedback: "no" });
  });
});
