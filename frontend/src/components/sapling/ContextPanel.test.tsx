// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { __resetScrollLocksForTests } from "@/lib/useScrollLock";

const viewport = vi.hoisted(() => ({ phone: false }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => viewport.phone, MOBILE_BREAKPOINT: 768 }));

import { ContextPanel, ContextSheet } from "./ContextPanel";

beforeEach(() => {
  vi.useFakeTimers();
  viewport.phone = false;
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  __resetScrollLocksForTests();
  document.body.style.removeProperty("overflow-y");
  document.body.style.removeProperty("overflow-x");
});

const settle = () => act(() => { vi.advanceTimersByTime(50); });

function Route() {
  return (
    <div>
      <button type="button">Before</button>
      <ContextPanel label="Learning route" triggerLabel="Show learning route" testid="ctx">
        <p>Functions · evidence collected</p>
        <a href="/library">Recursion workshop</a>
      </ContextPanel>
    </div>
  );
}

describe("ContextPanel", () => {
  it("is a labelled rail on desktop, with no trigger and no dialog", () => {
    render(<Route />);
    const rail = screen.getByRole("complementary", { name: "Learning route" });
    expect(rail).toHaveTextContent("Functions · evidence collected");
    expect(screen.queryByTestId("ctx-trigger")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("on a phone, moves the same content into one labelled sheet", () => {
    viewport.phone = true;
    render(<Route />);
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(screen.queryByText("Functions · evidence collected")).toBeNull();
    const trigger = screen.getByRole("button", { name: "Show learning route" });
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    settle();
    const sheet = screen.getByRole("dialog", { name: "Learning route" });
    expect(sheet).toHaveAttribute("aria-modal", "true");
    expect(sheet).toHaveClass("sheet--bottom");
    expect(sheet.closest(".sheet-backdrop")).toHaveClass("sapling-surface");
    expect(sheet).toHaveTextContent("Functions · evidence collected");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  it("moves focus inside, traps Tab, closes on Escape and returns focus to the trigger", () => {
    viewport.phone = true;
    render(<Route />);
    const trigger = screen.getByRole("button", { name: "Show learning route" });
    trigger.focus();
    fireEvent.click(trigger);
    settle();
    const sheet = screen.getByRole("dialog");
    expect(sheet.contains(document.activeElement)).toBe(true);

    const close = screen.getByRole("button", { name: "Close" });
    const link = screen.getByRole("link", { name: "Recursion workshop" });
    link.focus();
    fireEvent.keyDown(link, { key: "Tab" });
    expect(document.activeElement).toBe(close);
    close.focus();
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(link);

    fireEvent.keyDown(sheet, { key: "Escape" });
    settle();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("locks the shell's scroll container while open and releases it on close", () => {
    viewport.phone = true;
    render(
      <main data-scroll-container="" style={{ overflowY: "auto" }}>
        <Route />
      </main>,
    );
    const main = document.querySelector<HTMLElement>("[data-scroll-container]")!;
    fireEvent.click(screen.getByRole("button", { name: "Show learning route" }));
    settle();
    expect(main.style.overflowY).toBe("hidden");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    settle();
    expect(main.style.overflowY).toBe("auto");
  });

  it("can be driven by the caller (e.g. selecting a Library row opens it)", () => {
    viewport.phone = true;
    const onOpenChange = vi.fn();
    const { rerender } = render(
      <ContextPanel label="Selected material" open={false} onOpenChange={onOpenChange} hideTrigger>
        <p>Detail</p>
      </ContextPanel>,
    );
    expect(screen.queryByRole("button")).toBeNull();
    rerender(
      <ContextPanel label="Selected material" open onOpenChange={onOpenChange} hideTrigger>
        <p>Detail</p>
      </ContextPanel>,
    );
    settle();
    fireEvent.keyDown(screen.getByRole("dialog", { name: "Selected material" }), { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("ContextSheet", () => {
  it("can be a right drawer and still carries the token scope", () => {
    render(<ContextSheet open onClose={() => {}} title="Goal & plan" side="right"><p>Plan</p></ContextSheet>);
    const sheet = screen.getByRole("dialog", { name: "Goal & plan" });
    expect(sheet).toHaveClass("sheet--right");
    expect(sheet.closest(".sheet-backdrop")).toHaveClass("sapling-context-sheet");
  });
});
