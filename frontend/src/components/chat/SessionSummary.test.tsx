// @vitest-environment jsdom
/** Classic Learn's end-of-session summary (prompt 04): an honest wrap-up in a
 *  labelled modal dialog — no automatic celebration — with Escape to close. */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionSummary } from "./SessionSummary";

afterEach(cleanup);

describe("SessionSummary", () => {
  it("is a labelled dialog with honest copy, focus on Done, and Escape closes it", () => {
    const onClose = vi.fn();
    render(<SessionSummary summary={{ concepts_covered: ["Recursion"], time_spent_minutes: 12 } as never} onClose={onClose} />);
    const dialog = screen.getByRole("dialog", { name: "Session wrapped up." });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.textContent).toContain("12 minutes spent.");
    expect(dialog.textContent).toContain("Recursion");
    expect(dialog.textContent).not.toMatch(/nice|great job|mastered/i);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Done" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
