// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import React from "react";
import { __resetScrollLocksForTests } from "@/lib/useScrollLock";
import { StudyModal } from "./StudyModal";

afterEach(() => {
  cleanup();
  __resetScrollLocksForTests();
  document.body.style.removeProperty("overflow-y");
  document.body.style.removeProperty("overflow-x");
});

function open(over: Partial<React.ComponentProps<typeof StudyModal>> = {}) {
  const onClose = vi.fn();
  const utils = render(
    <div data-testid="page">
      <StudyModal open onClose={onClose} label="Quiz" width={760} maxHeight={820} top={110} gap={18} {...over}>
        <button type="button">Struggling and Learning</button>
      </StudyModal>
    </div>,
  );
  return { onClose, ...utils };
}

describe("StudyModal", () => {
  it("is a labelled modal dialog portalled to <body>, not inside the page", () => {
    open();
    const dlg = screen.getByRole("dialog", { name: "Quiz" });
    expect(dlg).toHaveAttribute("aria-modal", "true");
    // The scrim's old containing block was the hub: it must not be any more.
    expect(screen.getByTestId("page")).not.toContainElement(dlg);
    expect(screen.getByTestId("page")).not.toContainElement(screen.getByTestId("study-modal-backdrop"));
  });

  it("renders nothing while closed", () => {
    open({ open: false });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on Escape", () => {
    const { onClose } = open();
    fireEvent.keyDown(screen.getByRole("button", { name: "Struggling and Learning" }), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on a backdrop click but not on a click inside the card", () => {
    const { onClose } = open();
    fireEvent.click(screen.getByRole("button", { name: "Struggling and Learning" }));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("study-modal-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("locks the page's scroll container while open", () => {
    const { unmount } = open();
    expect(document.body.style.getPropertyValue("overflow-y")).toBe("hidden");
    unmount();
    expect(document.body.style.getPropertyValue("overflow-y")).toBe("");
  });
});
