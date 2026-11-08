// @vitest-environment jsdom
/**
 * The tutor handoff, on its own (R-6 / R1 §F). What matters here is the SEAM:
 * the two-call seeding pattern, the follow-ups landing on the same session,
 * the failure ladder, and the session being left open on close.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, act } from "@testing-library/react";
import { __resetScrollLocksForTests } from "@/lib/useScrollLock";
import { AskPanel, composeAskMessage, type AskSeed } from "./AskPanel";
import crisisFixture from "@/test-utils/crisisSupport.json";

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
      return <div>{children}</div>;
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

function renderPanel(over: Partial<React.ComponentProps<typeof AskPanel>> = {}) {
  const onClose = vi.fn();
  const view = render(
    <AskPanel
      open
      onClose={onClose}
      userId="user-1"
      conceptName="Recursion"
      courseId="course-cs101"
      courseLabel="CS101"
      seed={SEED}
      {...over}
    />,
  );
  return { ...view, onClose };
}

/** The session id the tutor opened with. */
const SESSION = "tutor-session-1";

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

describe("composeAskMessage", () => {
  it("says what happened, in the order the tutor needs it", () => {
    expect(composeAskMessage(SEED)).toBe(
      [
        "I got this quiz question wrong and want to understand why.",
        "",
        "Question: What is the purpose of a base case?",
        "I chose C: It increases the recursion depth",
        "The correct answer is B: It stops the recursion",
        "Explanation given: Without one the calls never end.",
        "",
        "Help me understand why.",
      ].join("\n"),
    );
  });
});

describe("AskPanel", () => {
  it("opens a session on the concept, then sends the composed context", async () => {
    renderPanel();

    await waitFor(() => expect(api.startSessionStream).toHaveBeenCalledTimes(1));
    // (userId, topic, mode, useSharedContext, courseId, ...)
    expect(api.startSessionStream.mock.calls[0].slice(0, 5)).toEqual([
      "user-1",
      "Recursion",
      "socratic",
      true,
      "course-cs101",
    ]);

    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(1));
    expect(api.streamChat.mock.calls[0][0]).toBe(SESSION);
    expect(api.streamChat.mock.calls[0][2]).toBe(composeAskMessage(SEED));

    // The greeting from the start call is deliberately not rendered.
    expect(screen.queryByText("Hi.")).toBeNull();
    await screen.findByText("The base case is the exit.");
    // ...and the seed itself is on screen as static context.
    expect(screen.getByTestId("quiz-ask-seed")).toHaveTextContent("You chose C");
    expect(screen.getByTestId("quiz-ask-seed")).toHaveTextContent("The answer is B");
  });

  it("renders tokens as they stream in", async () => {
    api.streamChat.mockImplementation(async (...args: unknown[]) => {
      const handlers = args[6] as { onToken?: (d: string) => void };
      handlers.onToken?.("Think about ");
      handlers.onToken?.("the exit condition.");
      return { reply: "Think about the exit condition." };
    });

    renderPanel();
    await screen.findByText("Think about the exit condition.");
  });

  it("sends a follow-up on the SAME session and never re-opens one", async () => {
    renderPanel();
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByTestId("quiz-ask-input"), {
      target: { value: "So what happens without it?" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("quiz-ask-send"));
    });

    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(2));
    expect(api.startSessionStream).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[1][0]).toBe(SESSION);
    expect(api.streamChat.mock.calls[1][2]).toBe("So what happens without it?");
    expect(screen.getByText("So what happens without it?")).toBeInTheDocument();
  });

  it("falls back to the JSON route when the stream produced nothing", async () => {
    api.streamChat.mockRejectedValueOnce(new Error("stream died"));
    renderPanel();

    await waitFor(() => expect(api.sendChat).toHaveBeenCalledTimes(1));
    expect(api.sendChat.mock.calls[0][0]).toBe(SESSION);
    await screen.findByText("The base case is the exit (json).");
    expect(screen.queryByTestId("quiz-ask-retry")).toBeNull();
  });

  it("surfaces a non-retryable failure inline, and Retry re-sends it", async () => {
    api.shouldFallBackToJson.mockReturnValue(false);
    api.streamChat.mockRejectedValueOnce(new Error("tool writes already landed"));
    renderPanel();

    const retry = await screen.findByTestId("quiz-ask-retry");
    expect(screen.getByRole("alert")).toHaveTextContent("tool writes already landed");
    expect(api.sendChat).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(retry);
    });
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(2));
    // The session opened for the first attempt is reused, not replaced.
    expect(api.startSessionStream).toHaveBeenCalledTimes(1);
    expect(api.streamChat.mock.calls[1][2]).toBe(composeAskMessage(SEED));
  });

  it("keeps a half-written answer when the stream dies mid-sentence (ADR 0020)", async () => {
    api.streamChat.mockImplementationOnce(async (...args: unknown[]) => {
      const handlers = args[6] as { onToken?: (d: string) => void };
      handlers.onToken?.("A base case is ");
      handlers.onToken?.("the branch that");
      throw new Error("the tutor was interrupted");
    });

    renderPanel();

    // The partial the student was already reading stays on screen, marked. It
    // is NOT blinked out and replaced by an error strip.
    await screen.findByText("A base case is the branch that");
    expect(screen.getByText(/Interrupted/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("the tutor was interrupted");
    // Tokens appeared, so the JSON rung is skipped: never silently re-run a
    // turn the student has already partly read.
    expect(api.sendChat).not.toHaveBeenCalled();

    // Retry drops the fragment rather than stacking a whole answer under it.
    await act(async () => {
      fireEvent.click(screen.getByTestId("quiz-ask-retry"));
    });
    await screen.findByText("The base case is the exit.");
    expect(screen.queryByText("A base case is the branch that")).toBeNull();
    expect(screen.queryByText(/Interrupted/)).toBeNull();
    expect(screen.queryByTestId("quiz-ask-retry")).toBeNull();
  });

  it("aborts an in-flight stream on unmount", async () => {
    let signal: AbortSignal | undefined;
    api.streamChat.mockImplementationOnce(async (...args: unknown[]) => {
      signal = (args[6] as { signal?: AbortSignal }).signal;
      return new Promise(() => {}); // never settles — the tab goes away first
    });

    const { unmount } = renderPanel();
    await waitFor(() => expect(signal).toBeDefined());
    expect(signal!.aborted).toBe(false);

    unmount();
    expect(signal!.aborted).toBe(true);
  });

  it("aborts an in-flight stream when the panel is closed, and re-asks on reopen", async () => {
    // Nobody is reading a stream behind a closed sheet, and its reply would
    // land in state on a panel that is gone.
    let signal: AbortSignal | undefined;
    api.streamChat.mockImplementationOnce(async (...args: unknown[]) => {
      signal = (args[6] as { signal?: AbortSignal }).signal;
      return new Promise(() => {}); // still mid-sentence when the sheet closes
    });

    const onClose = vi.fn();
    const props = {
      onClose,
      userId: "user-1",
      conceptName: "Recursion",
      courseId: "course-cs101",
      courseLabel: "CS101",
      seed: SEED,
    };
    const { rerender } = render(<AskPanel open {...props} />);
    await waitFor(() => expect(signal).toBeDefined());
    expect(signal!.aborted).toBe(false);

    await act(async () => {
      rerender(<AskPanel open={false} {...props} />);
    });
    expect(signal!.aborted).toBe(true);

    // The turn never produced an answer, so reopening the SAME question asks it
    // again rather than showing an empty thread with no way to get one.
    await act(async () => {
      rerender(<AskPanel open {...props} />);
    });
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(2));
    expect(api.streamChat.mock.calls[1][2]).toBe(composeAskMessage(SEED));
    await screen.findByText("The base case is the exit.");
  });

  // #762: closing the sheet is this panel's Stop. It used to drop the half
  // answer on the floor (and, mid-follow-up, wipe the whole conversation on
  // reopen); Learn keeps a stopped partial as "interrupted" with Retry.
  it("keeps a half-written answer as interrupted when the panel is closed mid-sentence", async () => {
    let signal: AbortSignal | undefined;
    api.streamChat.mockImplementationOnce(async (...args: unknown[]) => {
      const handlers = args[6] as { onToken?: (d: string) => void; signal?: AbortSignal };
      signal = handlers.signal;
      handlers.onToken?.("A base case is ");
      return new Promise(() => {}); // still mid-sentence when the sheet closes
    });

    const props = {
      onClose: vi.fn(),
      userId: "user-1",
      conceptName: "Recursion",
      courseId: "course-cs101",
      courseLabel: "CS101",
      seed: SEED,
    };
    const { rerender } = render(<AskPanel open {...props} />);
    await screen.findByText("A base case is");

    await act(async () => {
      rerender(<AskPanel open={false} {...props} />);
    });
    expect(signal!.aborted).toBe(true);
    await act(async () => {
      rerender(<AskPanel open {...props} />);
    });

    // The partial is still there, marked, with Retry — not silently gone and
    // not silently re-asked.
    expect(screen.getByText("A base case is")).toBeInTheDocument();
    expect(screen.getByText(/Interrupted/)).toBeInTheDocument();
    expect(api.streamChat).toHaveBeenCalledTimes(1);

    await act(async () => {
      fireEvent.click(screen.getByTestId("quiz-ask-retry"));
    });
    await screen.findByText("The base case is the exit.");
    expect(screen.queryByText("A base case is")).toBeNull();
    expect(api.streamChat.mock.calls[1][2]).toBe(composeAskMessage(SEED));
    expect(api.startSessionStream).toHaveBeenCalledTimes(1);
  });

  it("closing during a follow-up keeps the conversation so far, and offers Retry for the follow-up", async () => {
    const props = {
      onClose: vi.fn(),
      userId: "user-1",
      conceptName: "Recursion",
      courseId: "course-cs101",
      courseLabel: "CS101",
      seed: SEED,
    };
    const { rerender } = render(<AskPanel open {...props} />);
    await screen.findByText("The base case is the exit.");

    api.streamChat.mockImplementationOnce(() => new Promise(() => {}));
    fireEvent.change(screen.getByTestId("quiz-ask-input"), { target: { value: "And without it?" } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("quiz-ask-send"));
    });
    await act(async () => {
      rerender(<AskPanel open={false} {...props} />);
    });
    await act(async () => {
      rerender(<AskPanel open {...props} />);
    });

    expect(screen.getByText("The base case is the exit.")).toBeInTheDocument();
    expect(screen.getByText("And without it?")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-ask-retry")).toBeInTheDocument();
    // Not re-seeded: one session, and the seed was asked once.
    expect(api.startSessionStream).toHaveBeenCalledTimes(1);
    expect(api.streamChat).toHaveBeenCalledTimes(2);

    await act(async () => {
      fireEvent.click(screen.getByTestId("quiz-ask-retry"));
    });
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(3));
    expect(api.streamChat.mock.calls[2][2]).toBe("And without it?");
  });

  it("says what the tutor is doing before its first word (progress events)", async () => {
    api.streamChat.mockImplementationOnce(async (...args: unknown[]) => {
      const handlers = args[6] as { onProgress?: (step: string) => void };
      handlers.onProgress?.("search_course_materials");
      return new Promise(() => {});
    });
    renderPanel();
    expect(await screen.findByText("Searching your course materials…")).toBeInTheDocument();
    expect(screen.queryByText("Thinking…")).toBeNull();
  });

  it("leaves a finished turn alone when the panel closes and reopens", async () => {
    const onClose = vi.fn();
    const props = {
      onClose,
      userId: "user-1",
      conceptName: "Recursion",
      courseId: "course-cs101",
      courseLabel: "CS101",
      seed: SEED,
    };
    const { rerender } = render(<AskPanel open {...props} />);
    await screen.findByText("The base case is the exit.");

    await act(async () => {
      rerender(<AskPanel open={false} {...props} />);
    });
    await act(async () => {
      rerender(<AskPanel open {...props} />);
    });

    // Nothing was in flight to abort, so the conversation is where it was — no
    // second session, no repeated question.
    expect(api.startSessionStream).toHaveBeenCalledTimes(1);
    expect(api.streamChat).toHaveBeenCalledTimes(1);
    expect(screen.getByText("The base case is the exit.")).toBeInTheDocument();
  });

  it("names the quiz question on the session start (spec §13 A99: quiz_ask origin)", async () => {
    renderPanel({ quizAsk: { attemptId: "attempt-9", questionIndex: 2 } });

    await waitFor(() => expect(api.startSessionStream).toHaveBeenCalledTimes(1));
    // (…, courseId, modelPref, handlers, quizAsk)
    expect(api.startSessionStream.mock.calls[0][5]).toBeUndefined();
    expect(api.startSessionStream.mock.calls[0][7]).toEqual({ attemptId: "attempt-9", questionIndex: 2 });
    // the follow-ups ride the session it opened; nothing else carries the origin
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(1));
    expect(api.streamChat.mock.calls[0][0]).toBe(SESSION);
  });

  it("names the quiz question on the JSON start route too", async () => {
    api.startSessionStream.mockRejectedValueOnce(new Error("no stream"));
    renderPanel({ quizAsk: { attemptId: "attempt-9", questionIndex: 0 } });

    await waitFor(() => expect(api.startSession).toHaveBeenCalledTimes(1));
    // (userId, topic, mode, courseId, useSharedContext, modelPref, quizAsk)
    expect(api.startSession.mock.calls[0][6]).toEqual({ attemptId: "attempt-9", questionIndex: 0 });
  });

  it("opens an ordinary session when there is no quiz question to name", async () => {
    renderPanel();
    await waitFor(() => expect(api.startSessionStream).toHaveBeenCalledTimes(1));
    expect(api.startSessionStream.mock.calls[0][7]).toBeUndefined();
  });

  it("does not re-seed when the caller re-renders with an equal quizAsk object", async () => {
    const props = {
      onClose: vi.fn(),
      userId: "user-1",
      conceptName: "Recursion",
      courseId: "course-cs101",
      seed: SEED,
    };
    const { rerender } = render(
      <AskPanel open {...props} quizAsk={{ attemptId: "attempt-9", questionIndex: 1 }} />,
    );
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(1));
    rerender(<AskPanel open {...props} quizAsk={{ attemptId: "attempt-9", questionIndex: 1 }} />);
    await screen.findByText("The base case is the exit.");
    expect(api.startSessionStream).toHaveBeenCalledTimes(1);
    expect(api.streamChat).toHaveBeenCalledTimes(1);
  });

  it("uses the JSON start route when the streamed one falls over", async () => {
    api.startSessionStream.mockRejectedValueOnce(new Error("no stream"));
    renderPanel();

    await waitFor(() => expect(api.startSession).toHaveBeenCalledTimes(1));
    expect(api.startSession.mock.calls[0].slice(0, 4)).toEqual([
      "user-1",
      "Recursion",
      "socratic",
      "course-cs101",
    ]);
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(1));
  });

  it("leaves the tutor session open on close, and hands focus back", async () => {
    const trigger = document.createElement("button");
    trigger.setAttribute("data-testid", "outside-trigger");
    document.body.appendChild(trigger);
    const returnFocusTo = { current: trigger };

    const { rerender, onClose } = renderPanel({ returnFocusTo });
    await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(1));

    await act(async () => {
      fireEvent.click(screen.getByTestId("quiz-ask-panel-close"));
    });
    expect(onClose).toHaveBeenCalledTimes(1);

    await act(async () => {
      rerender(
        <AskPanel
          open={false}
          onClose={onClose}
          userId="user-1"
          conceptName="Recursion"
          courseId="course-cs101"
          courseLabel="CS101"
          seed={SEED}
          returnFocusTo={returnFocusTo}
        />,
      );
    });

    expect(api.endSession).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });

  // #761/#762: one turn_id per turn, unchanged across the stream, its JSON
  // fallback and a Retry — so a re-send of a turn that already persisted is
  // replayed by the server instead of answered twice.
  describe("turn_id", () => {
    const TURN_ID = /^[A-Za-z0-9_\-]{8,128}$/;

    it("the stream and its JSON fallback carry the same turn_id", async () => {
      api.streamChat.mockRejectedValueOnce(new Error("stream died"));
      renderPanel();
      await waitFor(() => expect(api.sendChat).toHaveBeenCalledTimes(1));
      const turnId = api.streamChat.mock.calls[0][7];
      expect(turnId).toMatch(TURN_ID);
      expect(api.sendChat.mock.calls[0][6]).toBe(turnId);
    });

    it("Retry re-sends the failed turn's turn_id; a follow-up gets a new one", async () => {
      api.shouldFallBackToJson.mockReturnValue(false);
      api.streamChat.mockRejectedValueOnce(new Error("tool writes already landed"));
      renderPanel();
      const retry = await screen.findByTestId("quiz-ask-retry");
      const first = api.streamChat.mock.calls[0][7];
      expect(first).toMatch(TURN_ID);

      api.streamChat.mockResolvedValueOnce({ reply: "Replayed answer.", replayed: true });
      await act(async () => {
        fireEvent.click(retry);
      });
      await screen.findByText("Replayed answer.");
      expect(api.streamChat.mock.calls[1][7]).toBe(first);
      expect(screen.getAllByText("Replayed answer.")).toHaveLength(1);

      fireEvent.change(screen.getByTestId("quiz-ask-input"), { target: { value: "And then?" } });
      await act(async () => {
        fireEvent.click(screen.getByTestId("quiz-ask-send"));
      });
      await waitFor(() => expect(api.streamChat).toHaveBeenCalledTimes(3));
      expect(api.streamChat.mock.calls[2][7]).toMatch(TURN_ID);
      expect(api.streamChat.mock.calls[2][7]).not.toBe(first);
    });
  });

  it("does nothing at all until it is opened", () => {
    renderPanel({ open: false });
    expect(api.startSessionStream).not.toHaveBeenCalled();
    expect(screen.queryByTestId("quiz-ask-panel")).toBeNull();
  });
});

describe("AskPanel — crisis support (docs/safety/crisis-support.md)", () => {
  it("shows the card in the thread instead of a tutor reply, and the student can keep asking", async () => {
    renderPanel();
    await screen.findByText("The base case is the exit.");
    api.streamChat.mockResolvedValueOnce({ reply: "the card as text", crisis_support: crisisFixture });
    fireEvent.change(screen.getByTestId("quiz-ask-input"), { target: { value: "honestly i want to die" } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("quiz-ask-send"));
    });
    const card = await screen.findByTestId("crisis-support-card");
    expect(card).toHaveTextContent(crisisFixture.title);
    expect(screen.queryByText("the card as text")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull(); // a card, not an error strip
    expect(screen.getByTestId("quiz-ask-input")).not.toBeDisabled();
  });

  it("a session start answered with the card opens no session and sends nothing", async () => {
    api.startSessionStream.mockResolvedValueOnce({ session_id: null, reply: "…", crisis_support: crisisFixture });
    renderPanel();
    expect(await screen.findByTestId("crisis-support-card")).toBeTruthy();
    expect(api.streamChat).not.toHaveBeenCalled();
    expect(api.sendChat).not.toHaveBeenCalled();
  });
});
