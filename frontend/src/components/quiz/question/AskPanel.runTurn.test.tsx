// @vitest-environment jsdom
/**
 * Characterization of `AskPanel`'s turn runner — the branches the main suite
 * (`AskPanel.test.tsx`) leaves implicit: the session-open ladder's failure
 * rungs, the error copy, a superseded turn's late resolution, and what the
 * thread shows while the JSON fallback is in flight.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, act } from "@testing-library/react";
import { __resetScrollLocksForTests } from "@/lib/useScrollLock";
import { AskPanel, composeAskMessage, type AskSeed } from "./AskPanel";

const api = vi.hoisted(() => ({
  startSessionStream: vi.fn(),
  startSession: vi.fn(),
  streamChat: vi.fn(),
  sendChat: vi.fn(),
  endSession: vi.fn(),
  shouldFallBackToJson: vi.fn(() => true),
  newTurnId: vi.fn(() => `turn-${Math.random().toString(36).slice(2, 14)}`),
}));
vi.mock("@/lib/api", () => api);

vi.mock("next/dynamic", () => ({
  default: () =>
    function MarkdownStub({ children }: { children: React.ReactNode }) {
      return <div data-testid="md">{children}</div>;
    },
}));

const SEED: AskSeed = {
  stem: "What is the purpose of a base case?",
  chosenLabel: "C",
  chosenText: "It increases the recursion depth",
  correctLabel: "B",
  correctText: "It stops the recursion",
  explanation: "Without one the calls never end.",
};

const SEED_2: AskSeed = { ...SEED, stem: "Why does the stack overflow?" };

const SESSION = "tutor-session-1";

const baseProps = {
  onClose: () => {},
  userId: "user-1",
  conceptName: "Recursion",
  courseId: "course-cs101" as string | null,
  courseLabel: "CS101",
  seed: SEED,
};

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

type Handlers = {
  onToken?: (d: string) => void;
  onProgress?: (s: string) => void;
  signal?: AbortSignal;
};

beforeEach(() => {
  vi.clearAllMocks();
  api.shouldFallBackToJson.mockReturnValue(true);
  api.startSessionStream.mockResolvedValue({ session_id: SESSION, reply: "Hi." });
  api.startSession.mockResolvedValue({ session_id: SESSION, initial_message: "Hi." });
  api.streamChat.mockResolvedValue({ reply: "The base case is the exit." });
  api.sendChat.mockResolvedValue({ reply: "The base case is the exit (json)." });
});

afterEach(() => {
  cleanup();
  __resetScrollLocksForTests();
});

describe("AskPanel runTurn — opening the session", () => {
  it("passes undefined (not null) for a missing course on both start routes", async () => {
    api.startSessionStream.mockRejectedValueOnce(new Error("no stream"));
    render(<AskPanel open {...baseProps} courseId={null} />);
    await waitFor(() => expect(api.startSession).toHaveBeenCalledTimes(1));
    expect(api.startSessionStream.mock.calls[0]).toEqual([
      "user-1",
      "Recursion",
      "socratic",
      true,
      undefined,
      undefined,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    ]);
    expect(api.startSession.mock.calls[0]).toEqual([
      "user-1",
      "Recursion",
      "socratic",
      undefined,
      true,
    ]);
  });

  it("surfaces a start failure the JSON route would repeat, without falling back", async () => {
    api.shouldFallBackToJson.mockReturnValue(false);
    api.startSessionStream.mockRejectedValueOnce(new Error("payload too large"));
    render(<AskPanel open {...baseProps} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("payload too large");
    expect(api.startSession).not.toHaveBeenCalled();
    expect(api.streamChat).not.toHaveBeenCalled();
  });

  it("errors when the streamed start returns no session id", async () => {
    api.startSessionStream.mockResolvedValueOnce({ reply: "Hi." });
    render(<AskPanel open {...baseProps} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The tutor didn't open a session.");
    expect(api.startSession).not.toHaveBeenCalled();
    expect(api.streamChat).not.toHaveBeenCalled();
  });

  it("errors when the JSON start returns an empty session id", async () => {
    api.startSessionStream.mockRejectedValueOnce(new Error("no stream"));
    api.startSession.mockResolvedValueOnce({ session_id: "", initial_message: "Hi." });
    render(<AskPanel open {...baseProps} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The tutor didn't open a session.");
    expect(api.streamChat).not.toHaveBeenCalled();
  });

  it("surfaces a JSON start failure", async () => {
    api.startSessionStream.mockRejectedValueOnce(new Error("no stream"));
    api.startSession.mockRejectedValueOnce(new Error("start-session 500"));
    render(<AskPanel open {...baseProps} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("start-session 500");
    expect(api.streamChat).not.toHaveBeenCalled();
  });

  it("an aborted start neither falls back nor reports an error", async () => {
    api.startSessionStream.mockImplementationOnce(
      (...args: unknown[]) =>
        new Promise((_res, rej) => {
          const { signal } = args[6] as Handlers;
          signal?.addEventListener("abort", () => rej(new Error("aborted")));
        }),
    );
    const { rerender } = render(<AskPanel open {...baseProps} />);
    await waitFor(() => expect(api.startSessionStream).toHaveBeenCalledTimes(1));
    await act(async () => {
      rerender(<AskPanel open={false} {...baseProps} />);
    });
    await act(async () => {});
    expect(api.startSession).not.toHaveBeenCalled();
    expect(api.shouldFallBackToJson).not.toHaveBeenCalled();
    expect(api.streamChat).not.toHaveBeenCalled();
  });

  it("a session opened by a superseded turn is not adopted", async () => {
    const first = deferred<{ session_id: string }>();
    api.startSessionStream
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce({ session_id: "session-B" });
    const { rerender } = render(<AskPanel open {...baseProps} />);
    await waitFor(() => expect(api.startSessionStream).toHaveBeenCalledTimes(1));

    await act(async () => {
      rerender(<AskPanel open {...baseProps} seed={SEED_2} />);
    });
    await screen.findByText("The base case is the exit.");
    expect(api.streamChat.mock.calls[0][0]).toBe("session-B");

    await act(async () => {
      first.resolve({ session_id: "session-A" });
    });
    // A's late session never ran a turn, and never replaced B's.
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByTestId("quiz-ask-input"), { target: { value: "More?" } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("quiz-ask-send"));
    });
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(2));
    expect(api.streamChat.mock.calls[1][0]).toBe("session-B");
  });
});

describe("AskPanel runTurn — the chat leg", () => {
  it("the JSON fallback carries the same args, and the thread shows nothing pending while it runs", async () => {
    const json = deferred<{ reply: string }>();
    api.streamChat.mockImplementationOnce(async (...args: unknown[]) => {
      (args[6] as Handlers).onProgress?.("search_course_materials");
      throw new Error("stream died");
    });
    api.sendChat.mockImplementationOnce(() => json.promise);
    render(<AskPanel open {...baseProps} />);
    await waitFor(() => expect(api.sendChat).toHaveBeenCalledTimes(1));
    const turnId = api.streamChat.mock.calls[0][7];
    expect(api.sendChat.mock.calls[0]).toEqual([
      SESSION,
      "user-1",
      composeAskMessage(SEED),
      "socratic",
      true,
      undefined,
      turnId,
    ]);
    // streaming + status were cleared before the JSON leg.
    expect(screen.queryByText("Searching your course materials…")).toBeNull();
    expect(screen.queryByText("Thinking…")).toBeNull();
    expect(screen.getByTestId("quiz-ask-send")).toBeDisabled();

    await act(async () => {
      json.resolve({ reply: "From JSON." });
    });
    expect(screen.getByText("From JSON.")).toBeInTheDocument();
  });

  it("the stream call's handler bag and positional args", async () => {
    render(<AskPanel open {...baseProps} />);
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(1));
    const call = api.streamChat.mock.calls[0];
    expect(call.slice(0, 6)).toEqual([
      SESSION,
      "user-1",
      composeAskMessage(SEED),
      "socratic",
      true,
      undefined,
    ]);
    expect(Object.keys(call[6] as object)).toEqual(["onToken", "onProgress", "signal"]);
    expect(typeof call[7]).toBe("string");
  });

  it("shows Thinking… before the first token and ignores unknown progress steps", async () => {
    api.streamChat.mockImplementationOnce(async (...args: unknown[]) => {
      (args[6] as Handlers).onProgress?.("some_unknown_tool");
      return new Promise(() => {});
    });
    render(<AskPanel open {...baseProps} />);
    expect(await screen.findByText("Thinking…")).toBeInTheDocument();
  });

  it("whitespace-only tokens don't count as tokens: the JSON rung still runs", async () => {
    api.streamChat.mockImplementationOnce(async (...args: unknown[]) => {
      (args[6] as Handlers).onToken?.("   ");
      throw new Error("stream died");
    });
    render(<AskPanel open {...baseProps} />);
    await screen.findByText("The base case is the exit (json).");
    expect(api.sendChat).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Interrupted/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a whitespace-only partial is not kept as an interrupted turn", async () => {
    api.shouldFallBackToJson.mockReturnValue(false);
    api.streamChat.mockImplementationOnce(async (...args: unknown[]) => {
      (args[6] as Handlers).onToken?.("  ");
      throw new Error("the tutor was interrupted");
    });
    render(<AskPanel open {...baseProps} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("the tutor was interrupted");
    expect(screen.queryByText(/Interrupted/)).toBeNull();
    expect(document.querySelectorAll(".quiz-ask__turn--assistant")).toHaveLength(0);
  });

  it("a JSON fallback failure is surfaced inline", async () => {
    api.streamChat.mockRejectedValueOnce(new Error("stream died"));
    api.sendChat.mockRejectedValueOnce(new Error("chat 502"));
    render(<AskPanel open {...baseProps} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("chat 502");
    expect(screen.queryByText(/Interrupted/)).toBeNull();
  });

  it("a non-Error failure reads as 'The tutor is unavailable.'", async () => {
    api.shouldFallBackToJson.mockReturnValue(false);
    api.streamChat.mockRejectedValueOnce("boom");
    render(<AskPanel open {...baseProps} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The tutor is unavailable.");
  });

  it("an empty reply still lands as an (empty) assistant turn", async () => {
    api.streamChat.mockResolvedValueOnce({});
    render(<AskPanel open {...baseProps} />);
    await waitFor(() =>
      expect(document.querySelectorAll(".quiz-ask__turn--assistant")).toHaveLength(1),
    );
    expect(document.querySelector(".quiz-ask__turn--assistant")).toHaveTextContent("");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByTestId("quiz-ask-input")).toBeInTheDocument();
  });

  it("an empty JSON reply also lands as an empty assistant turn", async () => {
    api.streamChat.mockRejectedValueOnce(new Error("stream died"));
    api.sendChat.mockResolvedValueOnce({ reply: null });
    render(<AskPanel open {...baseProps} />);
    await waitFor(() =>
      expect(document.querySelectorAll(".quiz-ask__turn--assistant")).toHaveLength(1),
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("Send is disabled while a turn runs and re-enabled after it settles", async () => {
    const pending = deferred<{ reply: string }>();
    api.streamChat.mockImplementationOnce(() => pending.promise);
    render(<AskPanel open {...baseProps} />);
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByTestId("quiz-ask-input"), { target: { value: "Hm?" } });
    expect(screen.getByTestId("quiz-ask-send")).toBeDisabled();
    await act(async () => {
      pending.resolve({ reply: "Done." });
    });
    expect(screen.getByText("Done.")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-ask-send")).not.toBeDisabled();
  });
});

describe("AskPanel runTurn — a superseded turn", () => {
  it("drops a superseded turn's late tokens, reply and error", async () => {
    let staleHandlers: Handlers | undefined;
    const stale = deferred<{ reply: string }>();
    api.streamChat
      .mockImplementationOnce(async (...args: unknown[]) => {
        staleHandlers = args[6] as Handlers;
        staleHandlers.onToken?.("old ");
        return stale.promise;
      })
      .mockImplementationOnce(() => new Promise(() => {}));

    const { rerender } = render(<AskPanel open {...baseProps} />);
    await screen.findByText("old");
    await act(async () => {
      rerender(<AskPanel open {...baseProps} seed={SEED_2} />);
    });
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(2));
    expect(staleHandlers!.signal!.aborted).toBe(true);

    await act(async () => {
      staleHandlers!.onToken?.("late token");
      staleHandlers!.onProgress?.("search_course_materials");
    });
    expect(screen.queryByText(/late token/)).toBeNull();
    expect(screen.queryByText("Searching your course materials…")).toBeNull();
    expect(screen.getByText("Thinking…")).toBeInTheDocument();

    await act(async () => {
      stale.resolve({ reply: "Stale reply." });
    });
    expect(screen.queryByText("Stale reply.")).toBeNull();
    // The live turn is still running.
    expect(screen.getByText("Thinking…")).toBeInTheDocument();
  });

  it("drops a superseded turn's failure (no alert, no interrupted partial)", async () => {
    const stale = deferred<{ reply: string }>();
    api.shouldFallBackToJson.mockReturnValue(false);
    api.streamChat
      .mockImplementationOnce(async (...args: unknown[]) => {
        (args[6] as Handlers).onToken?.("half ");
        return stale.promise;
      })
      .mockImplementationOnce(() => new Promise(() => {}));
    const { rerender } = render(<AskPanel open {...baseProps} />);
    await screen.findByText("half");
    await act(async () => {
      rerender(<AskPanel open {...baseProps} seed={SEED_2} />);
    });
    await act(async () => {
      stale.reject(new Error("stale failure"));
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/Interrupted/)).toBeNull();
    expect(screen.getByText("Thinking…")).toBeInTheDocument();
  });
});
