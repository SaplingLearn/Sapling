// @vitest-environment jsdom
/**
 * The reader while a guide is being written: the stream (outline, then
 * sections, then done), the banner and skeletons, polling when another tab
 * holds the claim, an error with Retry, and the two modes the reader starts
 * itself (Regenerate, and a guide that failed).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
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

import {
  generateGuide,
  getGuide,
  GuideGenerationError,
  type GenerationHandlers,
} from "@/lib/studyGuide/api";
import { ToastProvider } from "@/components/ToastProvider";
import type { GuideDetail } from "@/lib/studyGuide/types";

import { GuideReader } from "./GuideReader";
import { deferred, fixtureGuide, newGuide, outlineOf, renderReader, sectionOf } from "./readerTestKit";
import { POLL_MS } from "./useGeneration";

const mocks = { getGuide: vi.mocked(getGuide), generateGuide: vi.mocked(generateGuide) };
const GUIDE_ID = "guide-fixture-1";

/** The finished guide: the fixture with its queued section written. */
function finishedGuide(): GuideDetail {
  const guide = fixtureGuide({ new_materials: 0, read_sections: [] });
  sectionOf(guide, "s3").status = "written";
  return guide;
}

/** A generation the test drives: its handlers, and the promise it ends with. */
function controlledRun() {
  const run = deferred<GuideDetail>();
  let handlers: GenerationHandlers = {};
  mocks.generateGuide.mockImplementation((_user, _guide, _mode, given = {}) => {
    handlers = given;
    return run.promise;
  });
  return { run, handlers: () => handlers };
}

const conflict = () => Object.assign(new Error("Another run is writing this guide."), { status: 409 });

beforeEach(() => vi.resetAllMocks());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("a guide that is still being written", () => {
  it("streams: the outline fills the page, sections fill in one at a time, then it is ready", async () => {
    const finished = finishedGuide();
    const { run, handlers } = controlledRun();
    mocks.getGuide.mockResolvedValue(newGuide(finished));
    renderReader();

    // Before the outline: the banner and a skeleton, no guide yet.
    const banner = await screen.findByTestId("guide-generating");
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalledWith("u1", GUIDE_ID, "resume", expect.any(Object)));
    expect(screen.queryByTestId("guide-title")).not.toBeInTheDocument();

    act(() => handlers().onStatus?.("Reading your 3 materials", { step: 1, total: 6 }));
    expect(banner).toHaveTextContent("Reading your 3 materials");
    expect(banner).toHaveTextContent("Step 1 of 6");

    // The outline: header, takeaways and every section listed, none written.
    act(() => handlers().onOutline?.(outlineOf(finished)));
    expect(screen.getByTestId("guide-title")).toHaveTextContent("Control flow and functions");
    expect(screen.getByText(finished.content.takeaways[0])).toBeInTheDocument();
    expect(within(screen.getByTestId("guide-section-s1")).getByText("Writing this section")).toBeInTheDocument();
    expect(within(screen.getByTestId("guide-section-s2")).getByText("Queued")).toBeInTheDocument();
    expect(screen.getByTestId("guide-outline-s1")).toHaveTextContent("Writing");
    expect(screen.getByTestId("guide-outline-s2")).toHaveTextContent("Queued");
    expect(screen.queryByTestId("guide-block-s1-i2")).not.toBeInTheDocument();
    expect(screen.getByTestId("guide-section-read-s1")).toBeDisabled();
    expect(screen.getByTestId("guide-progress")).toHaveTextContent("0 of 4 sections read");

    // One section arrives: it is drawn, and the next one is the one in progress.
    act(() => {
      handlers().onStatus?.("Writing section 2 of 4: Functions", { step: 3, total: 6 });
      handlers().onSection?.(sectionOf(finished, "s1"));
    });
    expect(banner).toHaveTextContent("Step 3 of 6");
    expect(screen.getByTestId("guide-block-s1-i2")).toBeInTheDocument();
    expect(screen.getByTestId("guide-outline-s1")).toHaveTextContent("Written");
    expect(within(screen.getByTestId("guide-section-s2")).getByText("Writing this section")).toBeInTheDocument();
    // A block is not rewritten while the guide around it is.
    expect(screen.queryByTestId("guide-block-regenerate-s1-i2")).not.toBeInTheDocument();
    expect(screen.queryByTestId("guide-feedback-yes")).not.toBeInTheDocument();

    // Done: the finished guide replaces what was streamed.
    await act(async () => run.resolve(finished));
    expect(screen.queryByTestId("guide-generating")).not.toBeInTheDocument();
    expect(screen.getByText("Guide ready.")).toBeInTheDocument();
    expect(screen.getByTestId("guide-block-s2-i2")).toBeInTheDocument();
    expect(screen.getByTestId("guide-outline-s1")).toHaveTextContent("Struggling");
    expect(screen.getByTestId("guide-block-regenerate-s1-i2")).toBeInTheDocument();
    expect(screen.getByTestId("guide-feedback-yes")).toBeInTheDocument();
  });

  it("resumes a guide that already has its outline", async () => {
    controlledRun();
    mocks.getGuide.mockResolvedValue(fixtureGuide({ status: "generating" }));
    renderReader();
    expect(await screen.findByTestId("guide-generating")).toBeInTheDocument();
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalledWith("u1", GUIDE_ID, "resume", expect.any(Object)));
    // Written sections stay; the queued one is the one being written.
    expect(screen.getByTestId("guide-block-s1-i2")).toBeInTheDocument();
    expect(within(screen.getByTestId("guide-section-s3")).getByText("Writing this section")).toBeInTheDocument();
  });

  it("stops the stream when the reader is left", async () => {
    const { handlers } = controlledRun();
    mocks.getGuide.mockResolvedValue(newGuide(fixtureGuide()));
    const view = renderReader();
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalled());
    expect(handlers().signal?.aborted).toBe(false);
    view.unmount();
    expect(handlers().signal?.aborted).toBe(true);
  });

  it("sends one generate request under StrictMode's double mount", async () => {
    // Two would race for the claim: the second gets a 409 and only polls.
    controlledRun();
    mocks.getGuide.mockResolvedValue(newGuide(fixtureGuide()));
    render(
      <StrictMode>
        <ToastProvider>
          <GuideReader guideId={GUIDE_ID} />
        </ToastProvider>
      </StrictMode>,
    );
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalled());
    await act(async () => {});
    expect(mocks.generateGuide).toHaveBeenCalledTimes(1);
  });

  it("does not start a generation for a guide that is ready", async () => {
    mocks.getGuide.mockResolvedValue(fixtureGuide());
    renderReader();
    await screen.findByTestId("guide-title");
    expect(mocks.generateGuide).not.toHaveBeenCalled();
    expect(screen.queryByTestId("guide-generating")).not.toBeInTheDocument();
  });
});

describe("another tab is writing the guide", () => {
  it("polls the guide every three seconds until it is no longer generating", async () => {
    vi.useFakeTimers();
    const flush = (ms = 0) => act(() => vi.advanceTimersByTimeAsync(ms));
    const finished = finishedGuide();
    const partial = fixtureGuide({ status: "generating", read_sections: [] });
    mocks.generateGuide.mockRejectedValue(conflict());
    mocks.getGuide
      .mockResolvedValueOnce(newGuide(finished))
      .mockResolvedValueOnce(partial)
      .mockResolvedValueOnce(finished);
    renderReader();
    await flush();

    expect(mocks.generateGuide).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("guide-generating")).toHaveTextContent("This guide is being written in another tab");
    expect(screen.getByTestId("guide-generating")).not.toHaveTextContent("Step");
    expect(mocks.getGuide).toHaveBeenCalledTimes(1);

    // Not before three seconds.
    await flush(POLL_MS - 1);
    expect(mocks.getGuide).toHaveBeenCalledTimes(1);

    // First poll: still generating, and what the other tab has written shows.
    await flush(1);
    expect(mocks.getGuide).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("guide-generating")).toBeInTheDocument();
    expect(screen.getByTestId("guide-block-s1-i2")).toBeInTheDocument();
    expect(within(screen.getByTestId("guide-section-s3")).getByText("Writing this section")).toBeInTheDocument();

    // Second poll: ready.
    await flush(POLL_MS);
    expect(mocks.getGuide).toHaveBeenCalledTimes(3);
    expect(screen.queryByTestId("guide-generating")).not.toBeInTheDocument();
    expect(screen.getByText("Guide ready.")).toBeInTheDocument();
    expect(mocks.generateGuide).toHaveBeenCalledTimes(1);

    // And it stops there.
    await flush(POLL_MS * 2);
    expect(mocks.getGuide).toHaveBeenCalledTimes(3);
  });

  it("stops polling when the reader is left", async () => {
    vi.useFakeTimers();
    const flush = (ms = 0) => act(() => vi.advanceTimersByTimeAsync(ms));
    mocks.generateGuide.mockRejectedValue(conflict());
    mocks.getGuide.mockResolvedValue(newGuide(fixtureGuide()));
    const view = renderReader();
    await flush();
    view.unmount();
    await flush(POLL_MS * 3);
    expect(mocks.getGuide).toHaveBeenCalledTimes(1);
  });
});

describe("a generation that fails", () => {
  it("shows the reason with Retry, which resumes", async () => {
    mocks.generateGuide.mockRejectedValueOnce(new GuideGenerationError("The model is busy. Try again.", true));
    mocks.getGuide.mockResolvedValue(fixtureGuide({ status: "generating" }));
    const user = userEvent.setup();
    renderReader();

    const error = await screen.findByTestId("guide-generation-error");
    expect(error).toHaveTextContent("The model is busy. Try again.");
    expect(screen.queryByTestId("guide-generating")).not.toBeInTheDocument();
    // What was written before the failure is still there.
    expect(screen.getByTestId("guide-block-s1-i2")).toBeInTheDocument();

    const { run } = controlledRun();
    await user.click(screen.getByTestId("guide-generation-retry"));

    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalledTimes(2));
    expect(mocks.generateGuide).toHaveBeenLastCalledWith("u1", GUIDE_ID, "resume", expect.any(Object));
    expect(screen.queryByTestId("guide-generation-error")).not.toBeInTheDocument();
    expect(screen.getByTestId("guide-generating")).toBeInTheDocument();

    await act(async () => run.resolve(finishedGuide()));
    expect(screen.getByText("Guide ready.")).toBeInTheDocument();
  });

  it("offers Retry for a guide whose generation had failed before it was opened", async () => {
    mocks.getGuide.mockResolvedValue(fixtureGuide({ status: "failed" }));
    renderReader();
    expect(await screen.findByTestId("guide-generation-error")).toHaveTextContent("The guide could not be written.");
    expect(mocks.generateGuide).not.toHaveBeenCalled();
  });
});

describe("regenerating the whole guide", () => {
  it("runs the stream in regenerate mode from the menu", async () => {
    const { run, handlers } = controlledRun();
    mocks.getGuide.mockResolvedValue(fixtureGuide());
    const user = userEvent.setup();
    renderReader();
    await screen.findByTestId("guide-title");

    await user.click(screen.getByTestId("guide-menu"));
    await user.click(screen.getByTestId("guide-menu-regenerate"));

    await waitFor(() =>
      expect(mocks.generateGuide).toHaveBeenCalledWith("u1", GUIDE_ID, "regenerate", expect.any(Object)),
    );
    expect(screen.getByTestId("guide-generating")).toBeInTheDocument();
    expect(screen.queryByTestId("guide-menu-regenerate")).not.toBeInTheDocument();

    // The new outline replaces the old sections while they are rewritten.
    act(() => handlers().onOutline?.(outlineOf(fixtureGuide())));
    expect(screen.queryByTestId("guide-block-s1-i2")).not.toBeInTheDocument();
    expect(within(screen.getByTestId("guide-section-s1")).getByText("Writing this section")).toBeInTheDocument();

    await act(async () => run.resolve(finishedGuide()));
    expect(screen.getByTestId("guide-block-s1-i2")).toBeInTheDocument();
    expect(screen.queryByTestId("guide-updated")).not.toBeInTheDocument();
  });
});
