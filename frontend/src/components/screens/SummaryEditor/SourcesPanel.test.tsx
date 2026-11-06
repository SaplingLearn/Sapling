// @vitest-environment jsdom
// frontend/src/components/screens/SummaryEditor/SourcesPanel.test.tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

const mockGetDocuments = vi.fn();
const mockAddSource = vi.fn();
const mockRemoveSource = vi.fn();

vi.mock("@/lib/api", () => ({
  getDocuments: (...args: unknown[]) => mockGetDocuments(...args),
  addSummaryDocSource: (...args: unknown[]) => mockAddSource(...args),
  removeSummaryDocSource: (...args: unknown[]) => mockRemoveSource(...args),
}));

// SourcesPanel reads useToast from "../../ToastProvider" (relative to this
// file, src/components/ToastProvider.tsx). The real hook throws outside a
// mounted <ToastProvider>, which this test doesn't render — mock it the
// same way HistoryPanel.test.tsx does, with a stable module-scope spy
// object so useToast() returns the same reference across renders.
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

import { SourcesPanel } from "./SourcesPanel";
import type { SummaryDoc } from "@/lib/types";

afterEach(cleanup);

function makeDoc(sources: SummaryDoc["sources"]): SummaryDoc {
  return {
    id: "sd1",
    owner_user_id: "u1",
    primary_document_id: "doc1",
    content: { type: "doc", content: [] },
    created_at: "t0",
    updated_at: "t0",
    sources,
    pending_suggestions: [],
  };
}

describe("SourcesPanel", () => {
  it("calls onOpenSource with the document id when a source with an original is clicked", async () => {
    mockGetDocuments.mockResolvedValue({ documents: [] });
    const onOpenSource = vi.fn();
    const doc = makeDoc([{ document_id: "doc1", file_name: "notes.pdf", added_at: "t0", has_original: true }]);

    render(<SourcesPanel doc={doc} userId="u1" onDocChanged={() => {}} onOpenSource={onOpenSource} />);
    await userEvent.click(await screen.findByText("notes.pdf"));

    expect(onOpenSource).toHaveBeenCalledWith("doc1");
  });

  it("does not render a click affordance for a source with no stored original", async () => {
    mockGetDocuments.mockResolvedValue({ documents: [] });
    const doc = makeDoc([{ document_id: "doc2", file_name: "slides.pptx", added_at: "t0", has_original: false }]);

    render(<SourcesPanel doc={doc} userId="u1" onDocChanged={() => {}} onOpenSource={() => {}} />);
    const label = await screen.findByText("slides.pptx");

    expect(label.tagName).not.toBe("BUTTON");
  });

  it("still supports removing a non-primary source (pre-existing behavior)", async () => {
    mockGetDocuments.mockResolvedValue({ documents: [] });
    const updatedDoc = makeDoc([{ document_id: "doc1", file_name: "notes.pdf", added_at: "t0", has_original: false }]);
    mockRemoveSource.mockResolvedValue(updatedDoc);
    const onDocChanged = vi.fn();
    const doc = makeDoc([
      { document_id: "doc1", file_name: "notes.pdf", added_at: "t0", has_original: false },
      { document_id: "doc2", file_name: "extra.pdf", added_at: "t0", has_original: false },
    ]);

    render(<SourcesPanel doc={doc} userId="u1" onDocChanged={onDocChanged} onOpenSource={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Remove extra.pdf" }));

    await waitFor(() => expect(mockRemoveSource).toHaveBeenCalledWith("sd1", "u1", "doc2"));
    await waitFor(() => expect(onDocChanged).toHaveBeenCalledWith(updatedDoc));
  });
});
