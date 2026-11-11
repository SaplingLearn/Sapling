import { describe, it, expect, vi, beforeEach } from "vitest";
import crisisFixture from "@/test-utils/crisisSupport.json";
import {
  ABORTED,
  askErrorCopy,
  chatWithFallback,
  isCrisisStart,
  openTutorSession,
  quizAskOrigin,
  type ChatLeg,
} from "./askTurn";

const api = vi.hoisted(() => ({
  startSessionStream: vi.fn(),
  startSession: vi.fn(),
  streamChat: vi.fn(),
  sendChat: vi.fn(),
  shouldFallBackToJson: vi.fn(() => true),
}));
vi.mock("@/lib/api", () => api);

beforeEach(() => {
  vi.clearAllMocks();
  api.shouldFallBackToJson.mockReturnValue(true);
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
    await expect(chatWithFallback(l, { onToken, onProgress }, vi.fn())).resolves.toEqual({ text: "Because.", crisisSupport: null });
    expect(api.streamChat).toHaveBeenCalledWith(
      "s1", "u", "Why?", "socratic", true, undefined,
      { onToken, onProgress, signal: l.signal }, "turn-1",
    );
  });

  it("maps an empty streamed reply to ''", async () => {
    api.streamChat.mockResolvedValueOnce({});
    await expect(chatWithFallback(leg(), {}, vi.fn())).resolves.toEqual({ text: "", crisisSupport: null });
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
    ).resolves.toEqual({ text: "", crisisSupport: null });
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
    expect(isCrisisStart(opened as never)).toBe(true);
    expect(opened).toMatchObject({ text: "card", crisisSupport: { title: crisisFixture.title } });
  });

  it("carries a reply's crisis card", async () => {
    api.streamChat.mockResolvedValueOnce({ reply: "card", crisis_support: crisisFixture });
    const reply = await chatWithFallback(
      { sid: "s1", userId: "u", message: "m", turnId: "t", signal: new AbortController().signal, progress: { sawToken: false, partial: "" } },
      {},
      vi.fn(),
    );
    expect(reply).toMatchObject({ text: "card", crisisSupport: { title: crisisFixture.title } });
  });
});
