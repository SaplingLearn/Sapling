// @vitest-environment jsdom
// frontend/src/components/screens/SummaryEditor/HistoryPanel.test.tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

const mockListVersions = vi.fn();
const mockRestore = vi.fn();

vi.mock("@/lib/api", () => ({
  listSummaryDocVersions: (...args: unknown[]) => mockListVersions(...args),
  restoreSummaryDocVersion: (...args: unknown[]) => mockRestore(...args),
}));

import { HistoryPanel } from "./HistoryPanel";

afterEach(cleanup);

describe("HistoryPanel", () => {
  it("lists versions and restores one on request", async () => {
    mockListVersions.mockResolvedValue({
      versions: [
        { id: "v2", trigger: "ai_edit_kept", created_at: "2026-01-02T00:00:00Z", preview: "Shorter now." },
        { id: "v1", trigger: "initial", created_at: "2026-01-01T00:00:00Z", preview: "Original text." },
      ],
    });
    const restoredDoc = { id: "sd1" };
    mockRestore.mockResolvedValue(restoredDoc);
    const onDocChanged = vi.fn();

    render(<HistoryPanel summaryDocId="sd1" userId="u1" onDocChanged={onDocChanged} />);

    await waitFor(() => expect(screen.getByText("AI edit kept")).toBeInTheDocument());
    expect(screen.getByText("Created")).toBeInTheDocument();

    await userEvent.click(screen.getAllByText("Bring this back")[0]);

    expect(mockRestore).toHaveBeenCalledWith("sd1", "u1", "v2");
    await waitFor(() => expect(onDocChanged).toHaveBeenCalledWith(restoredDoc));
  });
});
