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

describe("ChatPanel composer (redesign prompt 04)", () => {
  it("Enter sends, Shift+Enter adds a line, and an IME composition never sends", () => {
    const onSend = vi.fn();
    render(<ChatPanel messages={[]} onSend={onSend} />);
    const field = screen.getByTestId("tutor-input");
    fireEvent.change(field, { target: { value: "かんじ" } });
    // composing (isComposing, or the keyCode-229 some browsers send)
    fireEvent.keyDown(field, { key: "Enter", isComposing: true });
    fireEvent.keyDown(field, { key: "Enter", keyCode: 229 });
    fireEvent.keyDown(field, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(field, { key: "Enter" });
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith("かんじ");
    expect((field as HTMLTextAreaElement).value).toBe("");
  });

  it("an empty or whitespace draft never sends; a disabled composer says why", () => {
    const onSend = vi.fn();
    const { rerender } = render(<ChatPanel messages={[]} onSend={onSend} />);
    fireEvent.change(screen.getByTestId("tutor-input"), { target: { value: "   " } });
    fireEvent.keyDown(screen.getByTestId("tutor-input"), { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    expect((screen.getByTestId("tutor-send") as HTMLButtonElement).disabled).toBe(true);
    rerender(<ChatPanel messages={[]} onSend={onSend} disabled disabledReason="Chat is paused." />);
    const field = screen.getByTestId("tutor-input");
    expect((field as HTMLTextAreaElement).disabled).toBe(true);
    const described = (field.getAttribute("aria-describedby") ?? "").split(" ");
    expect(described.map((id) => document.getElementById(id)?.textContent)).toContain("Chat is paused.");
  });

  it("while streaming: Stop is offered, sending is blocked, and the tokens stay out of the live log", () => {
    const onStop = vi.fn();
    render(
      <ChatPanel
        messages={[{ id: "u1", role: "user", content: "why?" }]}
        onSend={noop}
        onStop={onStop}
        streamingText="Partial tok"
      />,
    );
    const log = screen.getByRole("log");
    expect(log.textContent).toContain("why?");
    expect(log.textContent).not.toContain("Partial tok"); // not announced token by token
    expect(screen.getByTestId("tutor-messages").textContent).toContain("Partial tok"); // but visible
    expect((screen.getByTestId("tutor-input") as HTMLTextAreaElement).disabled).toBe(true);
    fireEvent.click(screen.getByTestId("tutor-stop"));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("a starter seed fills the field without sending", () => {
    const onSend = vi.fn();
    const { rerender } = render(<ChatPanel messages={[]} onSend={onSend} draftSeed="" draftSeedKey={0} />);
    rerender(<ChatPanel messages={[]} onSend={onSend} draftSeed="Explain " draftSeedKey={1} />);
    expect((screen.getByTestId("tutor-input") as HTMLTextAreaElement).value).toBe("Explain ");
    expect(onSend).not.toHaveBeenCalled();
  });
});

describe("ChatPanel reading position", () => {
  /** jsdom has no layout: give the transcript a scrollable geometry. */
  function geometry(el: HTMLElement, { height = 1000, client = 300, top = 700 } = {}) {
    Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => height });
    Object.defineProperty(el, "clientHeight", { configurable: true, get: () => client });
    el.scrollTop = top;
  }

  it("keeps a reader's place when a reply lands while they review history, and offers Jump to latest", () => {
    const first: ChatMsg[] = [{ id: "a1", role: "assistant", content: "one" }];
    const { rerender } = render(<ChatPanel messages={first} onSend={noop} />);
    const log = screen.getByTestId("tutor-messages");
    geometry(log, { top: 100 }); // scrolled well above the end
    fireEvent.scroll(log);
    rerender(<ChatPanel messages={[...first, { id: "a2", role: "assistant", content: "two" }]} onSend={noop} />);
    expect(log.scrollTop).toBe(100); // not yanked to the bottom
    fireEvent.click(screen.getByTestId("tutor-jump-latest"));
    expect(log.scrollTop).toBe(1000);
    expect(screen.queryByTestId("tutor-jump-latest")).toBeNull();
  });

  it("follows new content while the reader is at the end, and always after their own turn", () => {
    const first: ChatMsg[] = [{ id: "a1", role: "assistant", content: "one" }];
    const { rerender } = render(<ChatPanel messages={first} onSend={noop} />);
    const log = screen.getByTestId("tutor-messages");
    geometry(log, { top: 100 });
    fireEvent.scroll(log);
    // the student's own message brings the conversation to the end
    rerender(<ChatPanel messages={[...first, { id: "u2", role: "user", content: "mine" }]} onSend={noop} />);
    expect(log.scrollTop).toBe(1000);
    expect(screen.queryByTestId("tutor-jump-latest")).toBeNull();
  });
});

describe("ChatPanel Retry gating", () => {
  it("renders Retry disabled while the caller says a retry would conflict", () => {
    const onRetry = vi.fn();
    render(<ChatPanel messages={[interruptedMsg()]} onSend={noop} onRetry={onRetry} canRetry={() => false} />);
    const retry = screen.getByTestId("tutor-retry") as HTMLButtonElement;
    expect(retry.disabled).toBe(true);
    fireEvent.click(retry);
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("names why the turn stopped in words", () => {
    render(
      <ChatPanel
        messages={[interruptedMsg({ interruptedReason: "stopped" }), interruptedMsg({ id: "m-9", interruptedReason: "offline" })]}
        onSend={noop}
        onRetry={noop}
      />,
    );
    expect(screen.getByText("You stopped this reply.")).toBeTruthy();
    expect(screen.getByText("You're offline, so this reply didn't arrive.")).toBeTruthy();
  });
});
