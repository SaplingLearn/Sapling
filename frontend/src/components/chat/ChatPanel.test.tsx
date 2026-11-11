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

import { ChatPanel, tutorStepLabel, type ChatMsg } from "./ChatPanel";
import crisisFixture from "@/test-utils/crisisSupport.json";
import { crisisSupportOf } from "@/lib/crisisSupport";

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

describe("ChatPanel streaming status (ADR 0030)", () => {
  it("shows what the tutor is doing in place of Thinking… before the first word", () => {
    render(
      <ChatPanel
        messages={[]}
        onSend={noop}
        streamingText=""
        streamingStatus="Searching your course materials…"
      />,
    );
    expect(screen.getByText("Searching your course materials…")).toBeTruthy();
    expect(screen.queryByText("Thinking…")).toBeNull();
  });

  it("falls back to Thinking… with no status, and hides the status once text arrives", () => {
    const { rerender } = render(<ChatPanel messages={[]} onSend={noop} streamingText="" />);
    expect(screen.getByText("Thinking…")).toBeTruthy();
    rerender(
      <ChatPanel
        messages={[]}
        onSend={noop}
        streamingText="The chain rule says"
        streamingStatus="Searching your course materials…"
      />,
    );
    expect(screen.getByText("The chain rule says")).toBeTruthy();
    expect(screen.queryByText("Searching your course materials…")).toBeNull();
  });
});

describe("tutorStepLabel", () => {
  it("names every tool the tutor registers (agents/chat_tutor.py)", () => {
    for (const step of [
      "search_course_materials",
      "read_session_history_tool",
      "read_user_progress_tool",
      "apply_graph_update_tool",
      "update_mastery_tool",
      "read_graph_neighborhood",
      "read_concepts_for_user",
    ]) {
      expect(tutorStepLabel(step)).toMatch(/…$/);
    }
  });

  it("returns null for a step it does not know, so Thinking… stays", () => {
    expect(tutorStepLabel("final_result")).toBeNull();
  });
});

describe("ChatPanel crisis-support turn (docs/safety/crisis-support.md)", () => {
  it("renders the calm card in place of a tutor bubble, keeping the composer open", () => {
    const support = crisisSupportOf(crisisFixture)!;
    const onSend = vi.fn();
    render(
      <ChatPanel
        messages={[
          { id: "u-1", role: "user", content: "what I typed" },
          { id: "a-1", role: "assistant", content: "the card's copy as text", crisisSupport: support },
        ]}
        onSend={onSend}
      />,
    );
    const card = screen.getByTestId("crisis-support-card");
    expect(card.textContent).toContain(support.title);
    // the card, not the markdown bubble: the text rendering is not shown twice
    expect(screen.queryByText("the card's copy as text")).toBeNull();
    expect(screen.getByText("what I typed")).toBeTruthy();
    // "whenever you're ready": the student keeps studying from the same composer
    const input = screen.getByTestId("tutor-input") as HTMLTextAreaElement;
    expect(input.disabled).toBe(false);
    fireEvent.change(input, { target: { value: "ok, back to hash tables" } });
    fireEvent.click(screen.getByTestId("tutor-send"));
    expect(onSend).toHaveBeenCalledWith("ok, back to hash tables");
  });
});

describe("ChatPanel — keyboard and screen reader (spec §13 A135)", () => {
  const msg = (id: string, content: string, over: Partial<ChatMsg> = {}): ChatMsg => ({ id, role: "assistant", content, ...over });

  it("the log is a polite live region a keyboard can reach and scroll", () => {
    render(<ChatPanel messages={[msg("a", "hello")]} onSend={noop} />);
    const log = screen.getByRole("log", { name: "Conversation" });
    expect(log).toHaveAttribute("aria-live", "polite");
    expect(log.tabIndex).toBe(0);
  });

  it("a visually hidden row stays in the log; clearing the flag paints the same node", () => {
    const { rerender } = render(<ChatPanel messages={[msg("p", "Why does it stop?", { visuallyHidden: true })]} onSend={noop} />);
    const row = screen.getByText("Why does it stop?");
    const wrapper = row.closest("[data-visually-hidden]") as HTMLElement;
    expect(wrapper).not.toBeNull();
    expect(wrapper.style.position).toBe("absolute");
    expect(screen.getByRole("log")).toContainElement(row);
    rerender(<ChatPanel messages={[msg("p", "Why does it stop?")]} onSend={noop} />);
    expect(screen.getByText("Why does it stop?")).toBe(row);
    expect(row.closest("[data-visually-hidden]")).toBeNull();
  });

  it("a message sent from the composer gives it focus back when the reply has ended", () => {
    const { rerender } = render(<ChatPanel messages={[]} onSend={noop} streamingText={null} />);
    const input = screen.getByTestId("tutor-input") as HTMLTextAreaElement;
    input.focus();
    fireEvent.change(input, { target: { value: "why?" } });
    fireEvent.keyDown(input, { key: "Enter" });
    rerender(<ChatPanel messages={[]} onSend={noop} streamingText="" />);
    expect(input.disabled).toBe(true);
    input.blur(); // a browser drops focus from a control that becomes disabled
    rerender(<ChatPanel messages={[msg("r", "Because n reaches zero.")]} onSend={noop} streamingText={null} />);
    expect(input).toHaveFocus();
  });

  it("does not take focus back when something else has it by the time the reply ends", () => {
    const { rerender } = render(
      <>
        <button data-testid="elsewhere">elsewhere</button>
        <ChatPanel messages={[]} onSend={noop} streamingText={null} />
      </>,
    );
    const input = screen.getByTestId("tutor-input") as HTMLTextAreaElement;
    input.focus();
    fireEvent.change(input, { target: { value: "why?" } });
    fireEvent.keyDown(input, { key: "Enter" });
    rerender(
      <>
        <button data-testid="elsewhere">elsewhere</button>
        <ChatPanel messages={[]} onSend={noop} streamingText="" />
      </>,
    );
    screen.getByTestId("elsewhere").focus();
    rerender(
      <>
        <button data-testid="elsewhere">elsewhere</button>
        <ChatPanel messages={[]} onSend={noop} streamingText={null} />
      </>,
    );
    expect(screen.getByTestId("elsewhere")).toHaveFocus();
  });
});
