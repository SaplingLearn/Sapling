// @vitest-environment jsdom
/**
 * #866 Z08 (review): with the learning loop off — its kill switch, or the flag
 * turned off after the beta — the legacy Tutor still lists and resumes the
 * student's loop sessions. Their saved rows repeat class material verbatim (an
 * H2 passage, a worked sibling, a reference), so the resume payload marks them
 * (`session.loop`) and the transcript is drawn inert, as LoopLearn draws it.
 * Every other session (everything main can hold) still renders rich.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, fireEvent } from "@testing-library/react";

const nav = vi.hoisted(() => ({ search: "", replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("@/lib/useActiveSemester", () => ({
  useActiveSemester: () => ["", () => {}, true],
  courseInTerm: () => true,
}));
vi.mock("../DisclaimerModal", () => ({ DisclaimerModal: () => null }));
// The loop is off: Learn renders the legacy LearnInner.
vi.mock("../learn/useLoopStatus", () => ({ useLoopStatus: () => ({ status: false, retry: () => {} }) }));
vi.mock("../graph/KnowledgeGraph", () => ({ KnowledgeGraph: () => <div data-testid="kg" /> }));
// The real renderer (ChatPanel loads it lazily through next/dynamic).
vi.mock("next/dynamic", async () => {
  const { MarkdownChat } = await import("../chat/MarkdownChat");
  return { default: () => MarkdownChat };
});

const api = vi.hoisted(() => ({
  getSessions: vi.fn(),
  resumeSession: vi.fn(),
  getCourses: vi.fn(),
  getGraph: vi.fn(),
  describeConcept: vi.fn(),
}));
vi.mock("@/lib/api", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

import { Learn } from "./Learn";
import { ToastProvider } from "../ToastProvider";

class StubResizeObserver {
  constructor(private cb: (entries: { contentRect: { width: number } }[]) => void) {}
  observe() { this.cb([{ contentRect: { width: 300 } }]); }
  unobserve() {}
  disconnect() {}
}

const CLASS_MATERIAL = [
  "[Open the lab handout](https://evil.example/handout) before Friday.",
  "The portal is at https://lab4-portal.example/login.",
  "![the lab diagram](https://evil.example/pixel.png)",
  "::geogebra{id=abc123}",
].join("\n\n");

function resumed(id: string, loop: boolean | undefined) {
  return {
    session: { id, user_id: "u1", topic: "Titration", mode: "socratic", course_id: null,
      started_at: "2026-11-01T00:00:00Z", ended_at: null, ...(loop === undefined ? {} : { loop }) },
    messages: [{ id: "m1", role: "assistant", content: CLASS_MATERIAL, created_at: "2026-11-01T00:00:01Z" }],
  };
}

function sessionRow(id: string) {
  return { id, topic: "Titration", mode: "socratic", course_id: null, started_at: "2026-11-01T00:00:00Z",
    ended_at: null, message_count: 1, is_active: true };
}

const log = () => screen.getByTestId("tutor-messages");

async function resume(id: string) {
  nav.search = `resume=${id}`;
  render(<ToastProvider><Learn /></ToastProvider>);
  await waitFor(() => expect(log()).toHaveTextContent("before Friday"));
}

beforeEach(() => {
  vi.clearAllMocks();
  nav.search = "";
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = StubResizeObserver;
  api.getSessions.mockResolvedValue({ sessions: [sessionRow("sess-loop"), sessionRow("sess-legacy")] });
  api.getCourses.mockResolvedValue({ courses: [] });
  api.getGraph.mockResolvedValue({ nodes: [], edges: [], stats: {} });
  api.describeConcept.mockResolvedValue({ description: "" });
  api.resumeSession.mockImplementation(async (id: string) =>
    id === "sess-loop" ? resumed(id, true) : id === "sess-old-server" ? resumed(id, undefined) : resumed(id, false));
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("the legacy Tutor resuming a session (loop off)", () => {
  it("draws a learning-loop session's class material inert: no live link, fetch or embed", async () => {
    await resume("sess-loop");
    expect(log().querySelector("a")).toBeNull();
    expect(log().querySelector("img")).toBeNull();
    expect(log().querySelector("iframe")).toBeNull();
    expect(log().textContent).toContain("Open the lab handout (evil.example)");
  });

  it("draws every other session exactly as main does: links stay live", async () => {
    await resume("sess-legacy");
    expect(log().querySelector('a[href="https://evil.example/handout"]')).not.toBeNull();
    expect(log().querySelector("iframe")).not.toBeNull();
  });

  it("a payload without the marker renders rich, as main does", async () => {
    await resume("sess-old-server");
    expect(log().querySelector('a[href="https://evil.example/handout"]')).not.toBeNull();
  });

  it("leaving a loop session for another one puts the transcript back to rich", async () => {
    await resume("sess-loop");
    expect(log().querySelector("a")).toBeNull();
    fireEvent.click(screen.getByTestId("tutor-back-to-learn"));
    fireEvent.click(await screen.findByTestId("tutor-session-resume-sess-legacy"));
    await waitFor(() => expect(log().querySelector('a[href="https://evil.example/handout"]')).not.toBeNull());
  });
});
