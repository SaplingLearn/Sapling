// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, act } from "@testing-library/react";
import React from "react";
import { __resetScrollLocksForTests } from "@/lib/useScrollLock";
import { Sheet } from "./Sheet";

afterEach(() => {
  cleanup();
  __resetScrollLocksForTests();
  document.body.style.removeProperty("overflow-y");
  document.body.style.removeProperty("overflow-x");
});

function open(over: Partial<React.ComponentProps<typeof Sheet>> = {}) {
  const onClose = vi.fn();
  const utils = render(
    <Sheet open onClose={onClose} title="Ask about this" testid="quiz-ask-panel" {...over}>
      <p>Why is B the answer?</p>
      <button type="button">Send</button>
    </Sheet>,
  );
  return { onClose, ...utils };
}

describe("Sheet", () => {
  it("is a modal dialog labelled by its own title", () => {
    open();
    const panel = screen.getByRole("dialog", { name: "Ask about this" });
    expect(panel).toHaveAttribute("aria-modal", "true");
    expect(panel).toHaveClass("sheet", "sheet--right");
    expect(panel).toHaveTextContent("Why is B the answer?");
  });

  it("renders into a portal on document.body, over the page", () => {
    const { container } = open();
    // Nothing in the caller's own subtree…
    expect(container.querySelector(".sheet")).toBeNull();
    // …but present in the document.
    expect(document.body.querySelector(".sheet")).not.toBeNull();
  });

  it("renders nothing at all when closed", () => {
    render(
      <Sheet open={false} onClose={() => {}} title="Ask about this">
        <p>hidden</p>
      </Sheet>,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on Escape, on the close button, and on a backdrop click", () => {
    const first = open();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(first.onClose).toHaveBeenCalledTimes(1);
    cleanup();

    const second = open();
    fireEvent.click(screen.getByTestId("quiz-ask-panel-close"));
    expect(second.onClose).toHaveBeenCalledTimes(1);
    cleanup();

    const third = open();
    fireEvent.click(document.body.querySelector(".sheet-backdrop")!);
    expect(third.onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close when the click lands inside the panel", () => {
    const { onClose } = open();
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("names its close button and suffixes its testid", () => {
    open();
    const close = screen.getByRole("button", { name: "Close" });
    expect(close).toHaveAttribute("data-testid", "quiz-ask-panel-close");
  });

  it("traps Tab inside the panel", () => {
    open();
    const panel = screen.getByRole("dialog");
    const focusable = Array.from(panel.querySelectorAll("button"));
    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    last.focus();
    fireEvent.keyDown(panel, { key: "Tab" });
    expect(document.activeElement).toBe(first);

    first.focus();
    fireEvent.keyDown(panel, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("moves focus into the panel on open and restores it on close", () => {
    vi.useFakeTimers();
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    expect(document.activeElement).toBe(opener);

    const { unmount } = render(
      <Sheet open onClose={() => {}} title="Ask about this">
        <button type="button">Send</button>
      </Sheet>,
    );
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(document.activeElement).not.toBe(opener);
    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);

    unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
    vi.useRealTimers();
  });

  it("locks the scrolling container while open and releases it on close", () => {
    // The lock is Dialog's, inherited through useOverlayBehaviour — but §3
    // names it as a Sheet requirement, so it gets its own assertion.
    const scroller = document.createElement("div");
    scroller.setAttribute("data-scroll-container", "");
    document.body.appendChild(scroller);
    expect(scroller.style.getPropertyValue("overflow-y")).toBe("");

    const { unmount } = render(
      <Sheet open onClose={() => {}} title="Ask about this">
        <p>body</p>
      </Sheet>,
    );
    expect(scroller.style.getPropertyValue("overflow-y")).toBe("hidden");
    expect(scroller.style.getPropertyValue("overflow-x")).toBe("hidden");

    unmount();
    expect(scroller.style.getPropertyValue("overflow-y")).toBe("");
    scroller.remove();
  });

  it("takes its width as a custom property so the rule stays in the stylesheet", () => {
    open({ width: 560 });
    expect(screen.getByRole("dialog").style.getPropertyValue("--sheet-width")).toBe("560px");
  });
});
