// @vitest-environment jsdom
// frontend/src/components/screens/SummaryEditor/SummaryEditor.test.tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

// SummaryEditor imports useToast from "../../ToastProvider" (relative to
// this file, that's src/components/ToastProvider.tsx). The real hook
// throws outside a <ToastProvider>, which this test doesn't mount — mock
// it the same way Calendar.test.tsx etc. do for components that read
// useToast directly. The spies are built once at module scope (not
// inside the factory) so `useToast()` returns a stable reference across
// renders — a fresh object per call would make every callback that
// depends on `toast` (keepSuggestion, undoSuggestionLocal) a new
// reference on every render, which retriggers the decoration-sync effect
// and loops with @tiptap/react's internal re-render-on-transaction watch.
const toastSpies = {
  show: vi.fn(),
  dismiss: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warn: vi.fn(),
};
vi.mock("../../ToastProvider", () => ({
  useToast: () => toastSpies,
}));

const mockGetSummaryDoc = vi.fn();
const mockKeepSummaryDocSuggestion = vi.fn();
const mockUndoSummaryDocSuggestion = vi.fn();
const mockUpdateSummaryDocContent = vi.fn();

vi.mock("@/lib/api", () => ({
  getSummaryDoc: (...args: unknown[]) => mockGetSummaryDoc(...args),
  updateSummaryDocContent: (...args: unknown[]) => mockUpdateSummaryDocContent(...args),
  keepSummaryDocSuggestion: (...args: unknown[]) => mockKeepSummaryDocSuggestion(...args),
  undoSummaryDocSuggestion: (...args: unknown[]) => mockUndoSummaryDocSuggestion(...args),
  addSummaryDocSource: vi.fn(),
  removeSummaryDocSource: vi.fn(),
  askSummaryDocAgent: vi.fn(),
  listSummaryDocVersions: vi.fn(),
  restoreSummaryDocVersion: vi.fn(),
}));

import { SummaryEditor } from "./SummaryEditor";

afterEach(cleanup);

// jsdom implements neither Range.getClientRects/getBoundingClientRect nor
// document.elementFromPoint (ProseMirror's hit-testing + caret-coordinate
// paths call both — see prosemirror-view's singleRect/posAtCoords). Without
// these, every click/keyboard interaction against a mounted TipTap editor
// throws an uncaught "not a function" from inside prosemirror-view, which
// fails the overall vitest run even when the test's own assertions pass.
// Stub both with inert no-ops; only geometry-dependent behavior (actual
// pixel positions) is affected, and this test only cares about document
// content and click targeting by element, not coordinates.
if (typeof Range.prototype.getClientRects !== "function") {
  Range.prototype.getClientRects = () => ({
    length: 0,
    item: () => null,
    [Symbol.iterator]: function* () {},
  }) as unknown as DOMRectList;
}
if (typeof Range.prototype.getBoundingClientRect !== "function") {
  Range.prototype.getBoundingClientRect = () =>
    ({ top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
}
if (typeof document.elementFromPoint !== "function") {
  document.elementFromPoint = () => null;
}

const BASE_DOC = {
  id: "sd1", owner_user_id: "u1", primary_document_id: "doc1",
  content: {
    type: "doc",
    content: [{ type: "paragraph", content: [{ type: "text", text: "Hello world." }] }],
  },
  created_at: "t0", updated_at: "t0",
  sources: [{ document_id: "doc1", file_name: "Lecture 4.pdf", added_at: "t0" }],
  pending_suggestions: [
    {
      id: "sg1", anchor_from: 1, anchor_to: 6,
      instruction: "shorter", original_text: "Hello", proposed_text: "Hi",
      status: "pending", created_at: "t0",
    },
  ],
};

describe("SummaryEditor — stale anchor guard on Keep", () => {
  it("drops the suggestion without calling keepSummaryDocSuggestion when the anchored text changed", async () => {
    mockGetSummaryDoc.mockResolvedValue(BASE_DOC);
    render(<SummaryEditor summaryDocId="sd1" />);

    await waitFor(() => expect(screen.getByText("Hi")).toBeInTheDocument());

    // Simulate the underlying text having changed since the ask was made —
    // directly editing the doc so position 1-6 no longer reads "Hello".
    const editable = screen.getByTestId("summary-editor-content").querySelector('[contenteditable="true"]')!;
    await userEvent.click(editable);
    await userEvent.keyboard("{Control>}a{/Control}");
    await userEvent.keyboard("Totally different text now.");

    await userEvent.click(screen.getByRole("button", { name: "Keep it" }));

    expect(mockKeepSummaryDocSuggestion).not.toHaveBeenCalled();
  });
});
