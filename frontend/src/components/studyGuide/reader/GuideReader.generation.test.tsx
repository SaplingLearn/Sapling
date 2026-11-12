// @vitest-environment jsdom
/**
 * The reader while a guide is being written: the stream (outline, then
 * sections, then done), the banner and skeletons, waiting on (and taking over
 * from) another run that holds the guide, an error with Retry, a section that
 * failed, and Regenerate. Requests that are turned away, and which marks a
 * rewrite keeps, are in GuideReader.refusal.test.tsx and .rewrite.test.tsx.
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

import { RETRY_MS } from "./generationRun";
import { GuideReader } from "./GuideReader";
import { deferred, fixtureGuide, newGuide, outlineOf, renderReader, sectionOf } from "./readerTestKit";

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

  it("keeps the step within its total when the total shrinks once the outline is planned", async () => {
    const { handlers } = controlledRun();
    mocks.getGuide.mockResolvedValue(newGuide(finishedGuide()));
    renderReader();
    const banner = await screen.findByTestId("guide-generating");
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalled());
    const shown = (step: number, total: number) => {
      act(() => handlers().onStatus?.("Working", { step, total }));
      const bar = banner.querySelector<HTMLElement>("div[aria-hidden] > div");
      return [banner.textContent?.match(/Step \d+ of \d+/)?.[0], bar?.style.width];
    };

    // As the server counts them: before the outline is planned the guide may
    // still have every section its depth allows, and then it has three.
    expect(shown(1, 8)).toEqual(["Step 1 of 8", "13%"]);
    expect(shown(2, 8)).toEqual(["Step 2 of 8", "25%"]);
    expect(shown(3, 6)).toEqual(["Step 3 of 6", "50%"]);
    expect(shown(4, 6)).toEqual(["Step 4 of 6", "67%"]);
    expect(shown(5, 6)).toEqual(["Step 5 of 6", "83%"]);
    expect(shown(6, 6)).toEqual(["Step 6 of 6", "100%"]);
  });

  it("shows the guide and says it is ready when the stream is only its `done`", async () => {
    // Another request finished the guide first: this one is told so at once.
    const finished = finishedGuide();
    mocks.generateGuide.mockResolvedValue(finished);
    mocks.getGuide.mockResolvedValue(newGuide(finished));
    renderReader();

    expect(await screen.findByText("Guide ready.")).toBeInTheDocument();
    expect(mocks.generateGuide).toHaveBeenCalledTimes(1);
    expect(mocks.getGuide).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("guide-title")).toHaveTextContent("Control flow and functions");
    expect(screen.getByTestId("guide-block-s2-i2")).toBeInTheDocument();
    expect(screen.queryByTestId("guide-generating")).not.toBeInTheDocument();
    expect(screen.queryByTestId("guide-generation-error")).not.toBeInTheDocument();
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

describe("another run holds the guide", () => {
  const flush = (ms = 0) => act(() => vi.advanceTimersByTimeAsync(ms));
  const partial = () => fixtureGuide({ status: "generating", read_sections: [] });

  it("shows what that run has written, and asks to resume every three seconds until it is done", async () => {
    vi.useFakeTimers();
    const finished = finishedGuide();
    mocks.generateGuide.mockRejectedValue(conflict());
    mocks.getGuide
      .mockResolvedValueOnce(newGuide(finished))
      .mockResolvedValueOnce(partial())
      .mockResolvedValueOnce(finished);
    renderReader();
    await flush();

    // The 409 is followed at once by a re-read: the other run's sections show.
    expect(mocks.generateGuide).toHaveBeenCalledTimes(1);
    expect(mocks.getGuide).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("guide-generating")).toHaveTextContent("This guide is being written in another tab");
    expect(screen.getByTestId("guide-generating")).not.toHaveTextContent("Step");
    expect(screen.getByTestId("guide-block-s1-i2")).toBeInTheDocument();
    expect(within(screen.getByTestId("guide-section-s3")).getByText("Writing this section")).toBeInTheDocument();

    // Not before three seconds.
    await flush(RETRY_MS - 1);
    expect(mocks.generateGuide).toHaveBeenCalledTimes(1);

    // Then it asks to resume. Still held: the re-read says the guide is ready.
    await flush(1);
    expect(mocks.generateGuide).toHaveBeenCalledTimes(2);
    expect(mocks.generateGuide).toHaveBeenLastCalledWith("u1", GUIDE_ID, "resume", expect.any(Object));
    expect(mocks.getGuide).toHaveBeenCalledTimes(3);
    expect(screen.queryByTestId("guide-generating")).not.toBeInTheDocument();
    expect(screen.getByText("Guide ready.")).toBeInTheDocument();

    // And it stops there.
    await flush(RETRY_MS * 2);
    expect(mocks.generateGuide).toHaveBeenCalledTimes(2);
    expect(mocks.getGuide).toHaveBeenCalledTimes(3);
  });

  it("takes the guide over when the run that held it has stopped", async () => {
    vi.useFakeTimers();
    const run = deferred<GuideDetail>();
    let handlers: GenerationHandlers = {};
    mocks.generateGuide.mockRejectedValueOnce(conflict()).mockImplementationOnce((_user, _guide, _mode, given = {}) => {
      handlers = given;
      return run.promise;
    });
    // The tab that was writing closed: the guide stays `generating`, half written.
    mocks.getGuide.mockResolvedValueOnce(newGuide(finishedGuide())).mockResolvedValue(partial());
    renderReader();
    await flush();
    expect(within(screen.getByTestId("guide-section-s3")).getByText("Writing this section")).toBeInTheDocument();

    await flush(RETRY_MS);
    expect(mocks.generateGuide).toHaveBeenCalledTimes(2);
    expect(mocks.generateGuide).toHaveBeenLastCalledWith("u1", GUIDE_ID, "resume", expect.any(Object));

    // This reader's own stream now: its status, then the missing section.
    act(() => handlers.onStatus?.("Writing section 3 of 4: Scope", { step: 4, total: 6 }));
    expect(screen.getByTestId("guide-generating")).toHaveTextContent("Writing section 3 of 4: Scope");
    expect(screen.getByTestId("guide-generating")).toHaveTextContent("Step 4 of 6");

    await act(async () => run.resolve(finishedGuide()));
    expect(screen.queryByTestId("guide-generating")).not.toBeInTheDocument();
    expect(within(screen.getByTestId("guide-section-s3")).queryByText("Writing this section")).not.toBeInTheDocument();
    expect(screen.getByText("Guide ready.")).toBeInTheDocument();

    await flush(RETRY_MS * 2);
    expect(mocks.generateGuide).toHaveBeenCalledTimes(2);
  });

  it("shows the error banner when asking again fails for another reason", async () => {
    vi.useFakeTimers();
    mocks.generateGuide
      .mockRejectedValueOnce(conflict())
      .mockRejectedValueOnce(new GuideGenerationError("The model is busy. Try again.", true));
    mocks.getGuide.mockResolvedValueOnce(newGuide(finishedGuide())).mockResolvedValue(partial());
    renderReader();
    await flush();
    await flush(RETRY_MS);

    expect(screen.getByTestId("guide-generation-error")).toHaveTextContent("The model is busy. Try again.");
    expect(screen.queryByTestId("guide-generating")).not.toBeInTheDocument();
    await flush(RETRY_MS * 2);
    expect(mocks.generateGuide).toHaveBeenCalledTimes(2);
  });

  it("stops when the reader is left while it waits", async () => {
    vi.useFakeTimers();
    mocks.generateGuide.mockRejectedValue(conflict());
    mocks.getGuide.mockResolvedValue(partial());
    const view = renderReader();
    await flush();
    expect(mocks.generateGuide).toHaveBeenCalledTimes(1);
    view.unmount();
    await flush(RETRY_MS * 3);
    expect(mocks.generateGuide).toHaveBeenCalledTimes(1);
    expect(mocks.getGuide).toHaveBeenCalledTimes(2);
  });

  it("stops when the reader is left while the guide is being re-read", async () => {
    vi.useFakeTimers();
    const reread = deferred<GuideDetail>();
    mocks.generateGuide.mockRejectedValue(conflict());
    mocks.getGuide.mockResolvedValueOnce(partial()).mockReturnValueOnce(reread.promise);
    const view = renderReader();
    await flush();
    view.unmount();
    await act(async () => reread.resolve(partial()));
    await flush(RETRY_MS * 3);
    expect(mocks.generateGuide).toHaveBeenCalledTimes(1);
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
    // What had been written is still shown under the banner.
    expect(screen.getByTestId("guide-block-s1-i2")).toBeInTheDocument();
  });

  it("shows only the error and Retry for a failed guide with nothing written, and Retry resumes", async () => {
    const { run } = controlledRun();
    mocks.getGuide.mockResolvedValue({ ...newGuide(finishedGuide()), status: "failed" });
    const user = userEvent.setup();
    renderReader();

    expect(await screen.findByTestId("guide-generation-error")).toHaveTextContent("The guide could not be written.");
    // No empty guide under it: no title, no rail, no skeleton standing in.
    expect(screen.queryByTestId("guide-title")).not.toBeInTheDocument();
    expect(screen.queryByTestId("guide-progress")).not.toBeInTheDocument();
    expect(screen.queryByTestId("guide-ask-input")).not.toBeInTheDocument();
    expect(mocks.generateGuide).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("guide-generation-retry"));
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalledWith("u1", GUIDE_ID, "resume", expect.any(Object)));
    expect(screen.queryByTestId("guide-generation-error")).not.toBeInTheDocument();
    expect(screen.getByTestId("guide-generating")).toBeInTheDocument();

    await act(async () => run.resolve(finishedGuide()));
    expect(screen.getByTestId("guide-title")).toBeInTheDocument();
  });
});

describe("a section that could not be written", () => {
  /** A ready guide whose third section failed. */
  function guideWithFailedSection(): GuideDetail {
    const guide = fixtureGuide({ read_sections: [] });
    Object.assign(sectionOf(guide, "s3"), { status: "failed", items: [] });
    return guide;
  }

  it("says so in place, with Try again that runs a resume", async () => {
    const { run } = controlledRun();
    mocks.getGuide.mockResolvedValue(guideWithFailedSection());
    const user = userEvent.setup();
    renderReader();

    const section = await screen.findByTestId("guide-section-s3");
    expect(within(section).getByText("This section could not be written.")).toBeInTheDocument();
    expect(screen.getByTestId("guide-section-read-s3")).toBeDisabled();
    // The rest of the guide is there, and nothing is generating.
    expect(screen.getByTestId("guide-block-s1-i2")).toBeInTheDocument();
    expect(screen.queryByTestId("guide-section-retry-s1")).not.toBeInTheDocument();
    expect(mocks.generateGuide).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("guide-section-retry-s3"));
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalledWith("u1", GUIDE_ID, "resume", expect.any(Object)));
    expect(screen.getByTestId("guide-generating")).toBeInTheDocument();
    // The run writes the failed section: it is the one in progress now.
    expect(within(screen.getByTestId("guide-section-s3")).getByText("Writing this section")).toBeInTheDocument();
    expect(screen.queryByTestId("guide-section-retry-s3")).not.toBeInTheDocument();

    await act(async () => run.resolve(finishedGuide()));
    expect(screen.queryByTestId("guide-section-retry-s3")).not.toBeInTheDocument();
    expect(within(screen.getByTestId("guide-section-s3")).queryByText("This section could not be written.")).not.toBeInTheDocument();
  });
});

describe("a resume that finds the guide already written", () => {
  /** What `streamSSE` throws for the server's 422: another request finished the guide first. */
  const alreadyWritten = () =>
    Object.assign(new Error(JSON.stringify({ detail: "This guide is already written." })), { status: 422 });

  /** A ready guide whose third section failed. */
  function missingOne(): GuideDetail {
    const guide = fixtureGuide({ read_sections: [] });
    Object.assign(sectionOf(guide, "s3"), { status: "failed", items: [] });
    return guide;
  }

  it("shows the finished guide and says it is ready, with no error, when it had loaded as generating", async () => {
    mocks.generateGuide.mockRejectedValue(alreadyWritten());
    mocks.getGuide
      .mockResolvedValueOnce(fixtureGuide({ status: "generating", read_sections: [] }))
      .mockResolvedValue(finishedGuide());
    renderReader();

    expect(await screen.findByText("Guide ready.")).toBeInTheDocument();
    expect(screen.queryByTestId("guide-generation-error")).not.toBeInTheDocument();
    expect(screen.queryByTestId("guide-generating")).not.toBeInTheDocument();
    expect(within(screen.getByTestId("guide-section-s3")).queryByText("Writing this section")).not.toBeInTheDocument();
    expect(screen.getByTestId("guide-feedback-yes")).toBeInTheDocument();
    expect(mocks.generateGuide).toHaveBeenCalledTimes(1);
  });

  it("shows the finished guide without a toast when the guide on screen was already ready", async () => {
    mocks.generateGuide.mockRejectedValue(alreadyWritten());
    mocks.getGuide.mockResolvedValueOnce(missingOne()).mockResolvedValue(finishedGuide());
    const user = userEvent.setup();
    renderReader();

    // Another tab filled the section in before this one asked.
    await user.click(await screen.findByTestId("guide-section-retry-s3"));
    await waitFor(() => expect(screen.queryByTestId("guide-section-retry-s3")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.queryByTestId("guide-generating")).not.toBeInTheDocument());

    expect(screen.queryByTestId("guide-generation-error")).not.toBeInTheDocument();
    expect(screen.queryByText("Guide ready.")).not.toBeInTheDocument();
  });

  it("still shows the error when the guide read back has a section left to write", async () => {
    mocks.generateGuide.mockRejectedValue(new GuideGenerationError("You are out of AI credit for today.", false));
    mocks.getGuide.mockResolvedValue(missingOne());
    const user = userEvent.setup();
    renderReader();

    await user.click(await screen.findByTestId("guide-section-retry-s3"));

    expect(await screen.findByTestId("guide-generation-error")).toHaveTextContent("You are out of AI credit for today.");
    expect(screen.getByTestId("guide-generation-dismiss")).toBeInTheDocument();
    expect(screen.queryByText("Guide ready.")).not.toBeInTheDocument();
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

  it("shows the guide another Regenerate wrote when this one's stream is only its `done`", async () => {
    const rewritten = { ...finishedGuide(), title: "Loops, rewritten" };
    rewritten.content = { ...rewritten.content, title: rewritten.title };
    mocks.generateGuide.mockResolvedValue(rewritten);
    mocks.getGuide.mockResolvedValue(fixtureGuide());
    const user = userEvent.setup();
    renderReader();
    await screen.findByTestId("guide-title");

    await user.click(screen.getByTestId("guide-menu"));
    await user.click(screen.getByTestId("guide-menu-regenerate"));

    expect(await screen.findByText("Guide ready.")).toBeInTheDocument();
    expect(screen.getByTestId("guide-title")).toHaveTextContent("Loops, rewritten");
    expect(screen.queryByTestId("guide-generating")).not.toBeInTheDocument();
    expect(screen.queryByTestId("guide-generation-error")).not.toBeInTheDocument();
  });
});
