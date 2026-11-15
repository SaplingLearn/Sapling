// @vitest-environment jsdom
/**
 * The study guide's "ask the tutor" hand-off answered by the crisis screen
 * (docs/safety/crisis-support.md): the card shows over the guide and the
 * tutor is NOT opened — the crisis turn was not kept, so the session would
 * open on nothing.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, cleanup, render, renderHook, screen } from "@testing-library/react";
import crisisFixture from "@/test-utils/crisisSupport.json";

const { push, toast, api } = vi.hoisted(() => ({
  push: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warn: vi.fn() },
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
vi.mock("@/lib/api", () => api);

import { useTutorHandoff } from "./useTutorHandoff";

const CRISIS = { reply: "the card as text", graph_update: {}, mastery_changes: [], crisis_support: crisisFixture };

beforeEach(() => {
  api.startSessionStream.mockResolvedValue({ session_id: "s1", reply: "Hi." });
  api.streamChat.mockResolvedValue({ reply: "An answer." });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function ask() {
  const hook = renderHook(() => useTutorHandoff("u1", "c1"));
  await act(async () => {
    await hook.result.current.ask("Recursion", "i want to kill myself");
  });
  render(<>{hook.result.current.crisisDialog}</>);
  return hook;
}

describe("useTutorHandoff — crisis support", () => {
  it("a question answered with the card shows it and opens no tutor", async () => {
    api.streamChat.mockResolvedValueOnce(CRISIS);
    await ask();
    expect((await screen.findByRole("dialog")).textContent).toContain(crisisFixture.title);
    expect(push).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("a session start answered with the card sends nothing", async () => {
    api.startSessionStream.mockResolvedValueOnce({ session_id: null, ...CRISIS });
    await ask();
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(api.streamChat).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("an ordinary answer still opens the tutor on the session", async () => {
    await ask();
    expect(push).toHaveBeenCalledWith("/learn?resume=s1");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
