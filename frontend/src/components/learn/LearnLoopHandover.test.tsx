// @vitest-environment jsdom
/** #866 K49, end to end through Learn(): this tab's `learning_loop` flag says
 *  "off" (read a minute ago), so Learn shows the legacy tree with no probe;
 *  the server, which reads the gate per request, has turned the loop on and
 *  answers the legacy turn with its phase 409. The page then asks the server
 *  (the loop status probe) and hands itself to LoopLearn; with the loop truly
 *  off the same refusal changes nothing. */
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/learn",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
// One map for the whole test, as FlagsProvider holds one per read.
const flagMap = vi.hoisted(() => ({ flags: { learning_loop: "off" }, ready: true, fresh: true }));
vi.mock("@/context/FlagsContext", () => ({ useFlagMap: () => flagMap, useFlag: () => "off" }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("@/lib/useActiveSemester", () => ({ useActiveSemester: () => ["", () => {}, true], courseInTerm: () => true }));
vi.mock("../DisclaimerModal", () => ({ DisclaimerModal: () => null }));
vi.mock("../graph/KnowledgeGraph", () => ({ KnowledgeGraph: () => null }));
vi.mock("next/dynamic", () => ({
  default: () => function MarkdownStub({ children }: { children: React.ReactNode }) { return <div>{children}</div>; },
}));
vi.mock("./LoopLearn", () => ({ LoopLearn: () => <div data-testid="loop-phase" data-phase="probe" /> }));

const api = vi.hoisted(() => ({
  getLoopStatus: vi.fn(),
  getSessions: vi.fn(),
  getCourses: vi.fn(),
  getGraph: vi.fn(),
  resumeSession: vi.fn(),
  streamChat: vi.fn(),
  sendChat: vi.fn(),
}));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), ...api }));

import { Learn } from "../screens/Learn";
import { ToastProvider } from "../ToastProvider";

const phaseRefusal = () =>
  Object.assign(new Error(JSON.stringify({ detail: "finish the probe first" })), {
    status: 409,
    body: { detail: "finish the probe first" },
  });

beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  api.getSessions.mockResolvedValue({
    sessions: [{ id: "sess-a", topic: "Recursion", mode: "socratic", course_id: "c1", started_at: "2026-11-01T00:00:00Z", ended_at: null, message_count: 1, is_active: true }],
  });
  api.getCourses.mockResolvedValue({ courses: [] });
  api.getGraph.mockResolvedValue({ nodes: [], edges: [], stats: {} });
  api.resumeSession.mockResolvedValue({
    session: { id: "sess-a", topic: "Recursion", mode: "socratic", course_id: "c1" },
    messages: [{ role: "assistant", content: "A function calling itself." }],
  });
  api.streamChat.mockRejectedValue(phaseRefusal());
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function sendInLegacySession() {
  render(<ToastProvider><Learn /></ToastProvider>);
  fireEvent.click(await screen.findByTestId("tutor-session-resume-sess-a"));
  await screen.findByTestId("tutor-messages");
  expect(api.getLoopStatus).not.toHaveBeenCalled(); // a fresh "off": no probe, as before
  fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "my answer" } });
  fireEvent.click(screen.getByTestId("tutor-send"));
}

it("a turn the loop answered hands the page to LoopLearn once the server says the loop is on", async () => {
  api.getLoopStatus.mockResolvedValue({ active: true });
  await sendInLegacySession();
  expect(await screen.findByTestId("loop-phase")).toBeInTheDocument();
  expect(api.getLoopStatus).toHaveBeenCalledWith("u1");
  expect(screen.queryByTestId("tutor-messages")).toBeNull();
});

it("with the loop off on the server too, the legacy tree stays", async () => {
  api.getLoopStatus.mockResolvedValue({ active: false });
  await sendInLegacySession();
  await waitFor(() => expect(api.getLoopStatus).toHaveBeenCalledTimes(1));
  expect(screen.getByTestId("tutor-messages")).toBeInTheDocument();
  expect(screen.queryByTestId("loop-phase")).toBeNull();
});
