// @vitest-environment jsdom
/**
 * An Update or a Regenerate that does not go through: what the banner says,
 * what Retry asks for, when the banner can be put away, and a guide that is
 * held by another request (a 409).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor } from "@testing-library/react";
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

import { generateGuide, getGuide, GuideGenerationError, type GenerationHandlers } from "@/lib/studyGuide/api";
import type { GuideDetail } from "@/lib/studyGuide/types";

import { MAX_TRIES, RETRY_MS } from "./generationRun";
import { deferred, fixtureGuide, outlineOf, renderReader } from "./readerTestKit";

const mocks = { getGuide: vi.mocked(getGuide), generateGuide: vi.mocked(generateGuide) };
const lastMode = () => mocks.generateGuide.mock.calls.at(-1)?.[2];

/** What `streamSSE` throws for a response that is not 2xx: the body, and the status. */
const refused = (status: number, detail: string) =>
  Object.assign(new Error(JSON.stringify({ detail })), { status });

async function open() {
  mocks.getGuide.mockResolvedValue(fixtureGuide());
  renderReader();
  await screen.findByTestId("guide-title");
  return userEvent.setup();
}

async function regenerate(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("guide-menu"));
  await user.click(screen.getByTestId("guide-menu-regenerate"));
}

beforeEach(() => vi.resetAllMocks());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("a request the server turns away", () => {
  it("says why in the server's words, offers no Retry for a 422, and can be dismissed", async () => {
    mocks.generateGuide.mockRejectedValue(refused(422, "No new lectures have been added since this guide was made."));
    const user = await open();
    await user.click(screen.getByTestId("guide-update"));

    const banner = await screen.findByTestId("guide-generation-error");
    expect(banner).toHaveTextContent("No new lectures have been added since this guide was made.");
    // Asking again would get the same answer.
    expect(screen.queryByTestId("guide-generation-retry")).not.toBeInTheDocument();
    // The guide is as it was, and still usable under the banner.
    expect(screen.getByTestId("guide-block-s1-i2")).toBeInTheDocument();
    expect(screen.queryByText("Guide ready.")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("guide-generation-dismiss"));
    expect(screen.queryByTestId("guide-generation-error")).not.toBeInTheDocument();
    expect(screen.getByTestId("guide-update")).toBeEnabled();
  });

  it("retries the Regenerate that hit the hourly limit, not a resume", async () => {
    mocks.generateGuide.mockRejectedValueOnce(refused(429, "You have made a lot of guides this hour. Try again later."));
    const user = await open();
    await regenerate(user);

    expect(await screen.findByTestId("guide-generation-error")).toHaveTextContent("You have made a lot of guides this hour.");
    expect(lastMode()).toBe("regenerate");

    mocks.generateGuide.mockReturnValue(deferred<GuideDetail>().promise);
    await user.click(screen.getByTestId("guide-generation-retry"));
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalledTimes(2));
    expect(lastMode()).toBe("regenerate");
    expect(screen.queryByTestId("guide-generation-error")).not.toBeInTheDocument();
  });

  it("retries the Update that never reached the server", async () => {
    mocks.generateGuide.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const user = await open();
    await user.click(screen.getByTestId("guide-update"));

    expect(await screen.findByTestId("guide-generation-error")).toHaveTextContent("The guide could not be written.");
    mocks.generateGuide.mockReturnValue(deferred<GuideDetail>().promise);
    await user.click(screen.getByTestId("guide-generation-retry"));
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalledTimes(2));
    expect(lastMode()).toBe("update");
  });
});

describe("a run that stops part way", () => {
  /** Regenerate, and hand back the stream's callbacks and its end. */
  async function regenerating() {
    const run = deferred<GuideDetail>();
    let handlers: GenerationHandlers = {};
    mocks.generateGuide.mockImplementationOnce((_user, _guide, _mode, given = {}) => {
      handlers = given;
      return run.promise;
    });
    const user = await open();
    await regenerate(user);
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalledTimes(1));
    return { user, run, handlers: () => handlers };
  }

  it("resumes on Retry once its outline has replaced the guide, and cannot be dismissed", async () => {
    const { user, run, handlers } = await regenerating();
    act(() => handlers().onOutline?.(outlineOf(fixtureGuide())));
    await act(async () => run.reject(new GuideGenerationError("The model is busy. Try again.", true)));

    expect(screen.getByTestId("guide-generation-error")).toHaveTextContent("The model is busy. Try again.");
    // The sections are queued on the server now: only a resume writes them.
    expect(screen.queryByTestId("guide-generation-dismiss")).not.toBeInTheDocument();

    mocks.generateGuide.mockReturnValue(deferred<GuideDetail>().promise);
    await user.click(screen.getByTestId("guide-generation-retry"));
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalledTimes(2));
    expect(lastMode()).toBe("resume");
  });

  it("asks for the same thing again when it stopped before the outline", async () => {
    const { user, run } = await regenerating();
    await act(async () => run.reject(new GuideGenerationError("The model is busy. Try again.", true)));

    expect(screen.getByTestId("guide-generation-dismiss")).toBeInTheDocument();
    mocks.generateGuide.mockReturnValue(deferred<GuideDetail>().promise);
    await user.click(screen.getByTestId("guide-generation-retry"));
    await waitFor(() => expect(mocks.generateGuide).toHaveBeenCalledTimes(2));
    expect(lastMode()).toBe("regenerate");
  });

  it("offers no Retry when the stream says trying again will not help", async () => {
    const { run } = await regenerating();
    await act(async () => run.reject(new GuideGenerationError("You are out of AI credit for today.", false)));

    expect(screen.getByTestId("guide-generation-error")).toHaveTextContent("You are out of AI credit for today.");
    expect(screen.queryByTestId("guide-generation-retry")).not.toBeInTheDocument();
  });
});

describe("a guide held by another request", () => {
  const flush = (ms = 0) => act(() => vi.advanceTimersByTimeAsync(ms));
  const conflict = () => Object.assign(new Error("Another run is writing this guide."), { status: 409 });

  /** Open the reader and press Update, with fake timers running. */
  async function update() {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mocks.getGuide.mockResolvedValue(fixtureGuide());
    renderReader();
    await screen.findByTestId("guide-title");
    await user.click(screen.getByTestId("guide-update"));
    await flush();
  }

  it("keeps asking for the Update, and never calls a guide it did not touch ready", async () => {
    const run = deferred<GuideDetail>();
    // Held once (one block was being rewritten), then free.
    mocks.generateGuide.mockRejectedValueOnce(conflict()).mockReturnValueOnce(run.promise);
    await update();

    // The re-read says the guide is ready. That is not this Update's doing.
    expect(mocks.generateGuide).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Guide ready.")).not.toBeInTheDocument();
    expect(screen.getByTestId("guide-generating")).toBeInTheDocument();

    await flush(RETRY_MS);
    expect(mocks.generateGuide).toHaveBeenCalledTimes(2);
    expect(lastMode()).toBe("update");

    await act(async () => run.resolve(fixtureGuide({ new_materials: 0 })));
    expect(screen.getByText("Guide ready.")).toBeInTheDocument();
    expect(screen.getByTestId("guide-updated")).toBeInTheDocument();
  });

  it("gives up after a bounded number of tries, with a Retry for the same Update", async () => {
    mocks.generateGuide.mockRejectedValue(conflict());
    await update();
    await flush(RETRY_MS * MAX_TRIES);

    expect(mocks.generateGuide).toHaveBeenCalledTimes(MAX_TRIES);
    expect(screen.getByTestId("guide-generation-error")).toHaveTextContent("still being written somewhere else");
    expect(screen.queryByTestId("guide-generating")).not.toBeInTheDocument();
    expect(screen.queryByText("Guide ready.")).not.toBeInTheDocument();
    await flush(RETRY_MS * 2);
    expect(mocks.generateGuide).toHaveBeenCalledTimes(MAX_TRIES);

    mocks.generateGuide.mockReturnValue(deferred<GuideDetail>().promise);
    await act(async () => screen.getByTestId("guide-generation-retry").click());
    await flush();
    expect(lastMode()).toBe("update");
  });
});
