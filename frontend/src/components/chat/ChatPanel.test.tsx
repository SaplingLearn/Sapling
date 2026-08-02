// @vitest-environment jsdom
/**
 * ADR 0020 (#356 item 5): an interrupted tutor turn KEEPS its partial text,
 * renders an explicit "Interrupted" marker, and offers Retry. Nothing is
 * persisted server-side for such a turn (routes/learn.py persists only on
 * completion), so Retry re-dispatching the same turn is safe — that wiring
 * lives in Learn.tsx; this test pins the ChatPanel rendering contract the
 * streaming journey (frontend/e2e/streaming.spec.ts) anchors on:
 *   - tutor-interrupted marker on interrupted bubbles only
 *   - tutor-retry only when a retryText + onRetry are present
 *   - the partial content stays visible (never blanked)
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

import { ChatPanel, type ChatMsg } from "./ChatPanel";

vi.mock("../Icon", () => ({ Icon: () => null }));
// MarkdownChat is lazy-loaded via next/dynamic (heavy markdown stack); render
// plain text in its place so assertions see the message content synchronously.
vi.mock("next/dynamic", () => ({
  default: () =>
    function MarkdownStub({ children }: { children: React.ReactNode }) {
      return <div>{children}</div>;
    },
}));

afterEach(cleanup);

const noop = () => {};

function interruptedMsg(over: Partial<ChatMsg> = {}): ChatMsg {
  return {
    id: "m-1",
    role: "assistant",
    content: "partial reply text that must stay visible",
    interrupted: true,
    retryText: "original user question",
    ...over,
  };
}

describe("ChatPanel interrupted-turn treatment (ADR 0020)", () => {
  it("renders the marker, keeps the partial text, and fires onRetry with the message", () => {
    const onRetry = vi.fn();
    render(
      <ChatPanel
        messages={[
          { id: "m-0", role: "user", content: "original user question" },
          interruptedMsg(),
        ]}
        onSend={noop}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByTestId("tutor-interrupted")).toBeTruthy();
    expect(
      screen.getByText("partial reply text that must stay visible"),
    ).toBeTruthy();

    fireEvent.click(screen.getByTestId("tutor-retry"));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onRetry.mock.calls[0][0].retryText).toBe("original user question");
  });

  it("shows the marker even when the turn was stopped before any token", () => {
    // Stop before the first token: no partial text, but the turn still needs
    // the interrupted affordance — otherwise the user's message sits with no
    // reply and no recourse (the exact outcome ADR 0020 rejects).
    render(
      <ChatPanel
        messages={[interruptedMsg({ content: "" })]}
        onSend={noop}
        onRetry={noop}
      />,
    );
    expect(screen.getByTestId("tutor-interrupted")).toBeTruthy();
    expect(screen.getByTestId("tutor-retry")).toBeTruthy();
  });

  it("renders no interrupted chrome on settled messages", () => {
    render(
      <ChatPanel
        messages={[{ id: "m-2", role: "assistant", content: "a normal reply" }]}
        onSend={noop}
        onRetry={noop}
      />,
    );
    expect(screen.queryByTestId("tutor-interrupted")).toBeNull();
    expect(screen.queryByTestId("tutor-retry")).toBeNull();
  });

  it("omits Retry when no handler is wired (marker still shows)", () => {
    render(<ChatPanel messages={[interruptedMsg()]} onSend={noop} />);
    expect(screen.getByTestId("tutor-interrupted")).toBeTruthy();
    expect(screen.queryByTestId("tutor-retry")).toBeNull();
  });
});
