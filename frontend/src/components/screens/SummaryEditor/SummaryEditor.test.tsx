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
const mockAskSummaryDocAgent = vi.fn();
const mockGetOriginalDocumentUrl = vi.fn();
const mockGetDocumentExtractedText = vi.fn();

vi.mock("@/lib/api", () => ({
  getSummaryDoc: (...args: unknown[]) => mockGetSummaryDoc(...args),
  updateSummaryDocContent: (...args: unknown[]) => mockUpdateSummaryDocContent(...args),
  keepSummaryDocSuggestion: (...args: unknown[]) => mockKeepSummaryDocSuggestion(...args),
  undoSummaryDocSuggestion: (...args: unknown[]) => mockUndoSummaryDocSuggestion(...args),
  addSummaryDocSource: vi.fn(),
  removeSummaryDocSource: vi.fn(),
  askSummaryDocAgent: (...args: unknown[]) => mockAskSummaryDocAgent(...args),
  listSummaryDocVersions: vi.fn().mockResolvedValue({ versions: [] }),
  restoreSummaryDocVersion: vi.fn(),
  // SourcesPanel (wired into the right rail in Task 22) calls this on mount
  // to populate the "Add a source" list — without a resolved value here the
  // panel's effect throws into an unhandled rejection and the whole tree
  // unmounts before this test's own assertions ever run.
  getDocuments: vi.fn().mockResolvedValue({ documents: [] }),
  getOriginalDocumentUrl: (...args: unknown[]) => mockGetOriginalDocumentUrl(...args),
  getDocumentExtractedText: (...args: unknown[]) => mockGetDocumentExtractedText(...args),
}));

// SummaryEditor imports these from "./SourceViewer"/"./SourceTextViewer" and
// renders whichever one matches the opened source's file type. Stub both so
// a reference can be fired with a single click, without pulling in the real
// pdfjs-dist render pipeline (Task 11 covers that pipeline on its own).
vi.mock("./SourceViewer", () => ({
  SourceViewer: ({ onReference }: { onReference: (r: { kind: "text"; text: string }) => void }) => (
    <button data-testid="test-stub-fire-reference" onClick={() => onReference({ kind: "text", text: "stub" })}>
      fire reference
    </button>
  ),
}));
vi.mock("./SourceTextViewer", () => ({
  SourceTextViewer: ({ onReference }: { onReference: (r: { kind: "text"; text: string }) => void }) => (
    <button data-testid="test-stub-fire-reference" onClick={() => onReference({ kind: "text", text: "stub" })}>
      fire reference
    </button>
  ),
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
  sources: [{ document_id: "doc1", file_name: "Lecture 4.pdf", added_at: "t0", has_original: true }],
  pending_suggestions: [
    {
      id: "sg1", anchor_from: 1, anchor_to: 6,
      instruction: "shorter", original_text: "Hello", proposed_text: "Hi",
      proposed_content: [{ type: "paragraph", content: [{ type: "text", text: "Hi" }] }],
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

  it("inserts proposed_content (structured JSON), not proposed_text, when keeping an anchored suggestion", async () => {
    const mathSuggestion = {
      id: "sg-math", anchor_from: 1, anchor_to: 6,
      instruction: "add the formula", original_text: "Hello",
      proposed_text: "$F = ma$",
      proposed_content: [{
        type: "paragraph",
        content: [{ type: "math", attrs: { latex: "F = ma", block: false } }],
      }],
      status: "pending", created_at: "t0",
    };
    mockGetSummaryDoc.mockResolvedValue({ ...BASE_DOC, pending_suggestions: [mathSuggestion] });
    render(<SummaryEditor summaryDocId="sd1" />);

    await userEvent.click(await screen.findByRole("button", { name: "Keep it" }));

    await waitFor(() => expect(mockKeepSummaryDocSuggestion).toHaveBeenCalled());
    const [, , , content] = mockKeepSummaryDocSuggestion.mock.calls[0];
    const serialized = JSON.stringify(content);
    expect(serialized).toContain('"type":"math"');
    expect(serialized).toContain('"latex":"F = ma"');
    expect(serialized).not.toContain("$F = ma$");
  });
});

describe("SummaryEditor — source reference viewer", () => {
  it("opens a source as a split pane when its Sources-tab button is clicked", async () => {
    mockGetSummaryDoc.mockResolvedValue(BASE_DOC);
    mockGetOriginalDocumentUrl.mockResolvedValue({ url: "https://signed.example/doc1.pdf" });
    render(<SummaryEditor summaryDocId="sd1" />);
    await waitFor(() => expect(screen.getByText("Hi")).toBeInTheDocument());

    await userEvent.click(await screen.findByText("Lecture 4.pdf"));

    expect(await screen.findByTestId("summary-editor-source-pane")).toBeInTheDocument();
    expect(mockGetOriginalDocumentUrl).toHaveBeenCalledWith("doc1", "u1");
  });

  it("closes the split pane when the source tab is clicked again", async () => {
    mockGetSummaryDoc.mockResolvedValue(BASE_DOC);
    mockGetOriginalDocumentUrl.mockResolvedValue({ url: "https://signed.example/doc1.pdf" });
    render(<SummaryEditor summaryDocId="sd1" />);
    await waitFor(() => expect(screen.getByText("Hi")).toBeInTheDocument());

    await userEvent.click(await screen.findByText("Lecture 4.pdf"));
    await screen.findByTestId("summary-editor-source-pane");

    // Once open, SourcesPanel's own row for this source is no longer
    // rendered (the aside swaps to a short "Viewing..." notice instead) —
    // the ONLY remaining element with this text is the active tab button,
    // so this click is unambiguous.
    await userEvent.click(screen.getByRole("button", { name: "Lecture 4.pdf" }));

    expect(screen.queryByTestId("summary-editor-source-pane")).not.toBeInTheDocument();
  });

  it("forces anchor_from/anchor_to to null when asking with a reference attached", async () => {
    mockGetSummaryDoc.mockResolvedValue(BASE_DOC);
    mockGetOriginalDocumentUrl.mockResolvedValue({ url: "https://signed.example/doc1.pdf" });
    mockAskSummaryDocAgent.mockResolvedValue({
      id: "sg2", anchor_from: null, anchor_to: null, instruction: "add this",
      original_text: null, proposed_text: "Woven in.",
      proposed_content: [{ type: "paragraph", content: [{ type: "text", text: "Woven in." }] }],
      status: "pending", created_at: "t0",
    });
    render(<SummaryEditor summaryDocId="sd1" />);
    await waitFor(() => expect(screen.getByText("Hi")).toBeInTheDocument());

    await userEvent.click(await screen.findByText("Lecture 4.pdf"));
    await userEvent.click(await screen.findByTestId("test-stub-fire-reference"));

    await userEvent.type(screen.getByTestId("summary-editor-ask-input"), "add this");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => expect(mockAskSummaryDocAgent).toHaveBeenCalled());
    const [, , body] = mockAskSummaryDocAgent.mock.calls[0];
    expect(body.anchor_from).toBeNull();
    expect(body.anchor_to).toBeNull();
    expect(body.reference).toEqual({ kind: "text", text: "stub" });
  });
});
