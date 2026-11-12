// @vitest-environment jsdom
/**
 * Update and Regenerate, on the screen: which read marks and check answers a
 * rewritten guide keeps, which section shows as being written, and the rail
 * once an Update has finished.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/dynamic", async () => (await import("@/test-utils/mockNextDynamic")).mockNextDynamicModule());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/components/chat/MarkdownChat", () => ({
  MarkdownChat: ({ children }: { children: string }) => <p>{children}</p>,
}));
vi.mock("@/lib/studyGuide/api", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/studyGuide/api")>()),
  getGuide: vi.fn(),
  patchGuide: vi.fn(),
  generateGuide: vi.fn(),
  regenerateBlock: vi.fn(),
  answerCheck: vi.fn(),
}));

import { generateGuide, getGuide, patchGuide, type GenerationHandlers } from "@/lib/studyGuide/api";
import type { CheckBlock, GuideContent, GuideDetail } from "@/lib/studyGuide/types";

import { deferred, fixtureGuide, outlineOf, renderReader, sectionOf } from "./readerTestKit";

const mocks = {
  getGuide: vi.mocked(getGuide),
  patchGuide: vi.mocked(patchGuide),
  generateGuide: vi.mocked(generateGuide),
};

/** A ready guide the student has worked through: two sections read, the check answered. */
function studiedGuide(): GuideDetail {
  const guide = fixtureGuide({ read_sections: ["s1", "s2"], answers: { "s1-i8": { option_id: "b", correct: true } } });
  sectionOf(guide, "s3").status = "written";
  const check = sectionOf(guide, "s1").items.find(item => item.id === "s1-i8") as CheckBlock;
  check.correct_id = "b";
  check.explain_correct = "0, 2, 4 and 6 pass the test.";
  return guide;
}

/** The guide as the server sends a rewritten one: nothing read, nothing answered. */
function rewrittenGuide(): GuideDetail {
  const guide = fixtureGuide({ new_materials: 0, read_sections: [], answers: {} });
  sectionOf(guide, "s3").status = "written";
  return guide;
}

/** An update's outline: the named sections are kept as written, the rest queued. */
function outlineKeeping(guide: GuideDetail, ...kept: string[]): GuideContent {
  return {
    ...guide.content,
    sections: guide.content.sections.map(section =>
      kept.includes(section.id) ? section : { ...section, status: "queued", items: [] },
    ),
  };
}

/** Open the reader on a guide, with a generation the test drives. */
async function open(guide: GuideDetail) {
  const run = deferred<GuideDetail>();
  let handlers: GenerationHandlers = {};
  mocks.generateGuide.mockImplementation((_user, _guide, _mode, given = {}) => {
    handlers = given;
    return run.promise;
  });
  mocks.getGuide.mockResolvedValue(guide);
  renderReader();
  await screen.findByTestId("guide-title");
  return { user: userEvent.setup(), run, handlers: () => handlers };
}

async function regenerate(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("guide-menu"));
  await user.click(screen.getByTestId("guide-menu-regenerate"));
  await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalled());
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.patchGuide.mockResolvedValue({ read_sections: [], saved_at: null, feedback: null });
});
afterEach(cleanup);

describe("Regenerate whole guide", () => {
  it("starts the new guide unread and unanswered, though its ids are the old ones", async () => {
    const { user, run, handlers } = await open(studiedGuide());
    expect(screen.getByTestId("guide-progress")).toHaveTextContent("2 of 4 sections read");
    expect(screen.getByTestId("guide-check-result-s1-i8")).toHaveTextContent("Correct.");

    await regenerate(user);
    const fresh = rewrittenGuide();
    act(() => handlers().onOutline?.(outlineOf(fresh)));
    expect(screen.getByTestId("guide-progress")).toHaveTextContent("0 of 4 sections read");

    // The new first section lands on the old one's id, and so does its check.
    act(() => handlers().onSection?.(sectionOf(fresh, "s1")));
    expect(screen.getByTestId("guide-section-read-s1")).toHaveTextContent("Mark as read");
    expect(screen.getByTestId("guide-section-read-s1")).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByTestId("guide-check-result-s1-i8")).not.toBeInTheDocument();
    expect(screen.getByTestId("guide-check-option-s1-i8-b")).toHaveAttribute("aria-checked", "false");

    await act(async () => run.resolve(fresh));
    expect(screen.getByTestId("guide-progress")).toHaveTextContent("0 of 4 sections read");
    expect(screen.queryByTestId("guide-check-result-s1-i8")).not.toBeInTheDocument();
  });
});

describe("Update guide", () => {
  it("keeps the marks of the sections it keeps, and saves no mark for one it dropped", async () => {
    const guide = studiedGuide();
    const { user, handlers } = await open(guide);

    await user.click(screen.getByTestId("guide-update"));
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalledWith("u1", guide.id, "update", expect.any(Object)));
    // s1 is kept as written; s2 is being rewritten.
    act(() => handlers().onOutline?.(outlineKeeping(guide, "s1", "s3", "s4")));

    expect(screen.getByTestId("guide-section-read-s1")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("guide-check-result-s1-i8")).toHaveTextContent("Correct. 0, 2, 4 and 6 pass the test.");
    expect(screen.getByTestId("guide-progress")).toHaveTextContent("1 of 4 sections read");

    // A mark made during the update saves only ids the server still has.
    await user.click(screen.getByTestId("guide-section-read-s4"));
    expect(mocks.patchGuide).toHaveBeenCalledWith("u1", guide.id, { read_sections: ["s1", "s4"] });
  });

  it("ends with the guide up to date and the new-lectures notice gone", async () => {
    const { user, run } = await open(studiedGuide());
    expect(screen.getByTestId("guide-stale")).toBeInTheDocument();

    await user.click(screen.getByTestId("guide-update"));
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalled());
    await act(async () => run.resolve(rewrittenGuide()));

    expect(screen.getByTestId("guide-updated")).toHaveTextContent("Guide is up to date");
    expect(screen.queryByTestId("guide-stale")).not.toBeInTheDocument();
    expect(screen.queryByTestId("guide-update")).not.toBeInTheDocument();
  });
});

describe("which section is being written", () => {
  /** A guide cut off with its second section failed and its third still queued. */
  function cutOff(): GuideDetail {
    const guide = fixtureGuide({ status: "generating", read_sections: [] });
    Object.assign(sectionOf(guide, "s2"), { status: "failed", items: [] });
    return guide;
  }
  const waiting = (id: string) => within(screen.getByTestId(`guide-section-${id}`));

  it("is the first one not written on a resume, failed or queued", async () => {
    await open(cutOff());
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalledWith("u1", "guide-fixture-1", "resume", expect.any(Object)));
    expect(waiting("s2").getByText("Writing this section")).toBeInTheDocument();
    expect(screen.getByTestId("guide-outline-s2")).toHaveTextContent("Writing");
    expect(waiting("s3").getByText("Queued")).toBeInTheDocument();
  });

  it("moves past a section that fails again in this run", async () => {
    const guide = cutOff();
    const { handlers } = await open(guide);
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalled());

    act(() => handlers().onSection?.(sectionOf(guide, "s2")));

    expect(waiting("s2").getByText("This section could not be written.")).toBeInTheDocument();
    expect(waiting("s3").getByText("Writing this section")).toBeInTheDocument();
  });
});
