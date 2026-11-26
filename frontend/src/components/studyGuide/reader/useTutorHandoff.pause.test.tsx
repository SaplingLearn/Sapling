// @vitest-environment jsdom
/**
 * The study guide's "ask the tutor" hand-off when the learning loop has paused
 * the tutor for the student's AI budget (#866 F10): the pause copy, not the
 * generic "could not be opened" error, and the tutor is not opened.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";

const { push, toast, api } = vi.hoisted(() => ({
  push: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() },
  api: {
    startSessionStream: vi.fn(),
    startSession: vi.fn(),
    streamChat: vi.fn(),
    sendChat: vi.fn(),
    shouldFallBackToJson: vi.fn(() => true),
    newTurnId: vi.fn(() => "turn-12345678"),
  },
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));
vi.mock("@/components/ToastProvider", () => ({ useToast: () => toast }));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), ...api }));

import { ApiError } from "@/lib/api";
import { useTutorHandoff } from "./useTutorHandoff";

beforeEach(() => {
  api.startSessionStream.mockResolvedValue({ session_id: "s1", reply: "Hi." });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function ask() {
  const hook = renderHook(() => useTutorHandoff("u1", "c1"));
  await act(async () => {
    await hook.result.current.ask("Recursion", "Why does it stop?");
  });
  return hook;
}

describe("useTutorHandoff — an AI budget pause", () => {
  it("a stream that ends on its budget notice toasts the pause copy, not an error", async () => {
    api.streamChat.mockImplementation(async (_s: string, _u: string, _m: string, _mode: string, _ctx: boolean, _pref: unknown, h: { onBudget?: (n: object) => void }) => {
      h.onBudget?.({ level: "hard", reset_at: null, scope: "daily", session_capped: true });
      throw new Error("stream ended without a reply");
    });
    await ask();
    expect(toast.warn).toHaveBeenCalledWith("Tutor chat paused for this session. Practice and review keep working.");
    expect(toast.error).not.toHaveBeenCalled();
    expect(api.sendChat).not.toHaveBeenCalled(); // never a JSON retry the budget would refuse
    expect(push).not.toHaveBeenCalled();
  });

  it("a 429 'ai budget reached' on the session start is the pause too", async () => {
    api.startSessionStream.mockRejectedValue(new ApiError(JSON.stringify({ detail: "ai budget reached", reset_at: null }), 429));
    api.shouldFallBackToJson.mockReturnValue(false);
    await ask();
    expect(toast.warn).toHaveBeenCalledWith("Tutor chat paused for now. Practice and review keep working.");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("any other failure keeps the error", async () => {
    api.streamChat.mockRejectedValue(new Error("boom"));
    api.sendChat.mockRejectedValue(new Error("boom"));
    await ask();
    expect(toast.error).toHaveBeenCalledWith("The tutor could not be opened. Try again.");
    expect(toast.warn).not.toHaveBeenCalled();
  });
});
