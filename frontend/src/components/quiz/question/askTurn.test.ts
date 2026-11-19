import { describe, it, expect, vi, beforeEach } from "vitest";
import crisisFixture from "@/test-utils/crisisSupport.json";
import {
  ABORTED,
  askErrorCopy,
  BudgetPausedError,
  chatWithFallback,
  openTutorSession,
  quizAskOrigin,
  turnPauseOf,
  type ChatLeg,
} from "./askTurn";

const api = vi.hoisted(() => ({
  startSessionStream: vi.fn(),
  startSession: vi.fn(),
  streamChat: vi.fn(),
  sendChat: vi.fn(),
  shouldFallBackToJson: vi.fn(() => true),
  // the learning loop's budget pause (lib/api.ts): none unless a case says so
  budgetPauseOf: vi.fn((_err: unknown): { resetAt: string | null; sessionCapped: boolean } | null => null),
}));
vi.mock("@/lib/api", () => api);

beforeEach(() => {
  vi.clearAllMocks();
  api.shouldFallBackToJson.mockReturnValue(true);
  api.budgetPauseOf.mockReturnValue(null);
});

describe("askErrorCopy", () => {
  it("uses an Error's message", () => {
    expect(askErrorCopy(new Error("chat 502"))).toBe("chat 502");
  });
  it("falls back to generic copy for anything else", () => {
    expect(askErrorCopy("boom")).toBe("The tutor is unavailable.");
    expect(askErrorCopy(undefined)).toBe("The tutor is unavailable.");
  });
});

describe("openTutorSession", () => {
  it("returns the streamed session id", async () => {
    api.startSessionStream.mockResolvedValueOnce({ session_id: "s1" });
    const signal = new AbortController().signal;
    await expect(openTutorSession("u", "Recursion", "c1", signal)).resolves.toBe("s1");
    expect(api.startSessionStream).toHaveBeenCalledWith(
      "u", "Recursion", "socratic", true, "c1", undefined, { signal }, undefined,
    );
    expect(api.startSession).not.toHaveBeenCalled();
  });

  it("maps a missing streamed id to null", async () => {
    api.startSessionStream.mockResolvedValueOnce({});
    await expect(
      openTutorSession("u", "Recursion", null, new AbortController().signal),
    ).resolves.toBeNull();
  });

  it("returns ABORTED when the signal was aborted, without falling back", async () => {
    const controller = new AbortController();
    controller.abort();
    api.startSessionStream.mockRejectedValueOnce(new Error("aborted"));
    await expect(openTutorSession("u", "Recursion", "c1", controller.signal)).resolves.toBe(ABORTED);
    expect(api.shouldFallBackToJson).not.toHaveBeenCalled();
    expect(api.startSession).not.toHaveBeenCalled();
  });

  it("rethrows a failure the JSON route would repeat", async () => {
    const err = new Error("413");
    api.shouldFallBackToJson.mockReturnValueOnce(false);
    api.startSessionStream.mockRejectedValueOnce(err);
    await expect(
      openTutorSession("u", "Recursion", "c1", new AbortController().signal),
    ).rejects.toBe(err);
    expect(api.startSession).not.toHaveBeenCalled();
  });

  it("falls back to the JSON start route", async () => {
    api.startSessionStream.mockRejectedValueOnce(new Error("no stream"));
    api.startSession.mockResolvedValueOnce({ session_id: "s2" });
    await expect(
      openTutorSession("u", "Recursion", null, new AbortController().signal),
    ).resolves.toBe("s2");
    expect(api.startSession).toHaveBeenCalledWith("u", "Recursion", "socratic", undefined, true, undefined, undefined);
  });
});

describe("chatWithFallback", () => {
  const leg = (over: Partial<ChatLeg> = {}): ChatLeg => ({
    sid: "s1",
    userId: "u",
    message: "Why?",
    turnId: "turn-1",
    signal: new AbortController().signal,
    progress: { sawToken: false, partial: "" },
    ...over,
  });
  const onToken = () => {};
  const onProgress = () => {};

  it("returns the streamed reply, passing the handler bag through", async () => {
    api.streamChat.mockResolvedValueOnce({ reply: "Because." });
    const l = leg();
    await expect(chatWithFallback(l, { onToken, onProgress }, vi.fn())).resolves.toBe("Because.");
    expect(api.streamChat).toHaveBeenCalledWith(
      "s1", "u", "Why?", "socratic", true, undefined,
      { onToken, onProgress, onRetract: undefined, onBudget: expect.any(Function), signal: l.signal }, "turn-1",
    );
  });

  // ── the learning loop's stream: retract and the budget pause ──────────────

  type LoopHandlers = { onRetract?: (r: string) => void; onBudget?: (n: unknown) => void };
  const NOTICE = { level: "hard", reset_at: "2026-11-09T00:00:00Z", scope: "daily", session_capped: false };

  it("passes the caller's retract handler to the stream", async () => {
    const onRetract = vi.fn();
    api.streamChat.mockImplementationOnce(async (...args: unknown[]) => {
      (args[6] as LoopHandlers).onRetract?.("leak");
      return { reply: "The whole reply." };
    });
    await expect(chatWithFallback(leg(), { onRetract }, vi.fn())).resolves.toBe("The whole reply.");
    expect(onRetract).toHaveBeenCalledWith("leak");
  });

  it("a paused stream (its budget notice, then no reply) throws the pause — no JSON retry", async () => {
    const onBudget = vi.fn();
    api.streamChat.mockImplementationOnce(async (...args: unknown[]) => {
      (args[6] as LoopHandlers).onBudget?.(NOTICE);
      throw new Error("Chat stream ended without a done event.");
    });
    const beforeFallback = vi.fn();
    const failure = chatWithFallback(leg(), { onBudget }, beforeFallback);
    await expect(failure).rejects.toBeInstanceOf(BudgetPausedError);
    await expect(failure).rejects.toMatchObject({ paused: { resetAt: "2026-11-09T00:00:00Z", sessionCapped: false } });
    expect(onBudget).toHaveBeenCalledWith(NOTICE);
    expect(beforeFallback).not.toHaveBeenCalled();
    expect(api.sendChat).not.toHaveBeenCalled();
  });

  it("a budget notice before a served (template) reply resolves the reply", async () => {
    api.streamChat.mockImplementationOnce(async (...args: unknown[]) => {
      (args[6] as LoopHandlers).onBudget?.(NOTICE);
      return { reply: "A worked example." };
    });
    await expect(chatWithFallback(leg(), {}, vi.fn())).resolves.toBe("A worked example.");
  });

  it("a failure after tokens is a failure, budget notice or not (the partial survives)", async () => {
    const err = new Error("interrupted");
    const l = leg();
    api.streamChat.mockImplementationOnce(async (...args: unknown[]) => {
      (args[6] as LoopHandlers).onBudget?.(NOTICE);
      l.progress.sawToken = true;
      throw err;
    });
    await expect(chatWithFallback(l, {}, vi.fn())).rejects.toBe(err);
  });

  it("maps an empty streamed reply to ''", async () => {
    api.streamChat.mockResolvedValueOnce({});
    await expect(chatWithFallback(leg(), {}, vi.fn())).resolves.toBe("");
  });

  it("returns ABORTED when the signal was aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    api.streamChat.mockRejectedValueOnce(new Error("aborted"));
    const beforeFallback = vi.fn();
    await expect(
      chatWithFallback(leg({ signal: controller.signal }), {}, beforeFallback),
    ).resolves.toBe(ABORTED);
    expect(beforeFallback).not.toHaveBeenCalled();
    expect(api.sendChat).not.toHaveBeenCalled();
  });

  it("rethrows once a token was seen, without asking whether to fall back", async () => {
    const err = new Error("cut off");
    api.streamChat.mockRejectedValueOnce(err);
    const beforeFallback = vi.fn();
    await expect(
      chatWithFallback(leg({ progress: { sawToken: true, partial: "half" } }), {}, beforeFallback),
    ).rejects.toBe(err);
    expect(api.shouldFallBackToJson).not.toHaveBeenCalled();
    expect(beforeFallback).not.toHaveBeenCalled();
  });

  it("rethrows a failure the JSON route would repeat", async () => {
    const err = new Error("non-retryable");
    api.shouldFallBackToJson.mockReturnValueOnce(false);
    api.streamChat.mockRejectedValueOnce(err);
    await expect(chatWithFallback(leg(), {}, vi.fn())).rejects.toBe(err);
    expect(api.sendChat).not.toHaveBeenCalled();
  });

  it("runs beforeFallback, then the JSON route with the same turn_id", async () => {
    const order: string[] = [];
    api.streamChat.mockRejectedValueOnce(new Error("stream died"));
    api.sendChat.mockImplementationOnce(async () => {
      order.push("sendChat");
      return { reply: null };
    });
    await expect(
      chatWithFallback(leg(), {}, () => order.push("beforeFallback")),
    ).resolves.toBe("");
    expect(order).toEqual(["beforeFallback", "sendChat"]);
    expect(api.sendChat).toHaveBeenCalledWith("s1", "u", "Why?", "socratic", true, undefined, "turn-1");
  });
});

describe("the quiz_ask origin and the crisis card (spec §13 A99; docs/safety/crisis-support.md)", () => {
  it("builds the origin only from both parts", () => {
    expect(quizAskOrigin("a1", 0)).toEqual({ attemptId: "a1", questionIndex: 0 });
    expect(quizAskOrigin(undefined, 0)).toBeUndefined();
    expect(quizAskOrigin("a1", undefined)).toBeUndefined();
  });

  it("sends the origin on both start routes", async () => {
    const origin = { attemptId: "a1", questionIndex: 2 };
    const signal = new AbortController().signal;
    api.startSessionStream.mockRejectedValueOnce(new Error("no stream"));
    api.startSession.mockResolvedValueOnce({ session_id: "s2" });
    await expect(openTutorSession("u", "Recursion", null, signal, origin)).resolves.toBe("s2");
    expect(api.startSessionStream.mock.calls[0][7]).toEqual(origin);
    expect(api.startSession.mock.calls[0][6]).toEqual(origin);
  });

  it("returns the crisis card instead of a session", async () => {
    api.startSessionStream.mockResolvedValueOnce({ session_id: null, reply: "card", crisis_support: crisisFixture });
    const opened = await openTutorSession("u", "Recursion", null, new AbortController().signal);
    expect(opened).toMatchObject({ crisis: { title: crisisFixture.title } });
  });

  it("carries a reply's crisis card", async () => {
    api.streamChat.mockResolvedValueOnce({ reply: "card", crisis_support: crisisFixture });
    const reply = await chatWithFallback(
      { sid: "s1", userId: "u", message: "m", turnId: "t", signal: new AbortController().signal, progress: { sawToken: false, partial: "" } },
      {},
      vi.fn(),
    );
    expect(reply).toMatchObject({ crisis: { title: crisisFixture.title } });
  });
});

describe("turnPauseOf", () => {
  it("reads the stream's pause, a 429 'ai budget reached', or nothing", () => {
    const paused = { resetAt: null, sessionCapped: true };
    expect(turnPauseOf(new BudgetPausedError(paused))).toEqual(paused);
    const refused = new Error("429");
    api.budgetPauseOf.mockImplementation((e: unknown) => (e === refused ? paused : null));
    expect(turnPauseOf(refused)).toEqual(paused);
    expect(turnPauseOf(new Error("500"))).toBeNull();
  });
});
