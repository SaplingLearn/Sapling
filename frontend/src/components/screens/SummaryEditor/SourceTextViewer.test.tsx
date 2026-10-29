// @vitest-environment jsdom
// frontend/src/components/screens/SummaryEditor/SourceTextViewer.test.tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

import { SourceTextViewer } from "./SourceTextViewer";

afterEach(cleanup);

describe("SourceTextViewer", () => {
  it("renders the extracted text", () => {
    render(<SourceTextViewer text="Mitosis has four phases." onReference={() => {}} />);
    expect(screen.getByTestId("summary-editor-source-text")).toHaveTextContent(
      "Mitosis has four phases.",
    );
  });

  it("calls onReference with the selected text range on mouseup", async () => {
    const onReference = vi.fn();
    render(<SourceTextViewer text="Mitosis has four phases." onReference={onReference} />);
    const node = screen.getByTestId("summary-editor-source-text");

    // jsdom's Selection API is limited — simulate a real selection by
    // setting it directly on window.getSelection(), then firing mouseup,
    // which is what the component actually listens for.
    const range = document.createRange();
    range.selectNodeContents(node.firstChild!);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);

    // userEvent.click's own mousedown handling collapses the Selection we
    // just set (it recreates it at the click point, mirroring real browser
    // mousedown behavior), so restore it before firing the mouseup the
    // component actually listens for.
    await userEvent.click(node);
    selection.removeAllRanges();
    selection.addRange(range);
    node.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));

    expect(onReference).toHaveBeenCalledWith({ kind: "text", text: "Mitosis has four phases." });
  });

  it("does not call onReference when nothing is selected", () => {
    const onReference = vi.fn();
    render(<SourceTextViewer text="Some text." onReference={onReference} />);
    window.getSelection()?.removeAllRanges();
    screen.getByTestId("summary-editor-source-text").dispatchEvent(
      new MouseEvent("mouseup", { bubbles: true }),
    );
    expect(onReference).not.toHaveBeenCalled();
  });
});
