// @vitest-environment jsdom
/**
 * The /admin/check-items review queue (spec §13 A113; GitHub #695).
 *
 * What these pin:
 *   - the admin gate (a non-admin gets the refusal and no request is made);
 *   - each entry shows its lint flags, its reports by reason, the question with
 *     its key marked, the final answer and the reference;
 *   - Approve calls the API and every row of that course question leaves;
 *   - Retire takes two clicks (it withdraws the question course-wide and,
 *     spec §13 A123, voids every student's results on it — the toast says how many);
 *   - a quarantined item is marked, and approving it says it is restored;
 *   - a failed action keeps the row and toasts; a failed load offers a retry;
 *   - nothing to review says so; a retire-pending item cannot be approved.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

const userState = vi.hoisted(() => ({ isAdmin: true }));
vi.mock("@/context/UserContext", () => ({ useUser: () => userState }));
vi.mock("../TopBar", () => ({ TopBar: ({ title }: { title: string }) => <div>{title}</div> }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn() }));
vi.mock("../ToastProvider", () => ({ useToast: () => toast }));
const api = vi.hoisted(() => ({
  adminCheckItemQueue: vi.fn(),
  adminApproveCheckItem: vi.fn(),
  adminRetireCheckItem: vi.fn(),
}));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), ...api }));

import type { AdminCheckItemEntry, AdminCheckItemQueue } from "@/lib/api";
import { AdminCheckItems } from "./AdminCheckItems";

const entry = (over: Partial<AdminCheckItemEntry> = {}): AdminCheckItemEntry => ({
  id: "i1",
  course_id: "c1",
  concept_key: "recursion",
  question_hash: "qh1",
  format: "mc_reason",
  difficulty: 2,
  lint_flags: [],
  reports: { wrong_answer: 0, unclear: 0, not_from_my_course: 0, total: 0 },
  last_reported_at: null,
  status: null,
  reviewed_at: null,
  retire_pending: false,
  quarantined: false,
  prompt: "Which case stops the recursion?",
  options: [
    { letter: "A", text: "the base case", correct: true },
    { letter: "B", text: "a loop", correct: false },
  ],
  final_answer: "the base case",
  reference_answer: "The base case returns without recursing. Final answer: the base case.",
  ...over,
});

const queue = (items: AdminCheckItemEntry[], over: Partial<AdminCheckItemQueue> = {}): AdminCheckItemQueue => ({
  items, count: items.length, page_size: 100, quarantine_min_reporters: 2, ...over,
});

beforeEach(() => {
  userState.isAdmin = true;
  Object.values(api).forEach((f) => f.mockReset());
  Object.values(toast).forEach((f) => f.mockReset());
});
afterEach(cleanup);

describe("AdminCheckItems", () => {
  it("refuses a non-admin without a request", () => {
    userState.isAdmin = false;
    render(<AdminCheckItems />);
    expect(screen.getByText("You don't have admin access.")).toBeTruthy();
    expect(api.adminCheckItemQueue).not.toHaveBeenCalled();
  });

  it("lists each item with its flags, reports by reason, key and reference", async () => {
    api.adminCheckItemQueue.mockResolvedValue(
      queue(
        [
          entry({ reports: { wrong_answer: 2, unclear: 0, not_from_my_course: 1, total: 3 } }),
          entry({ id: "i2", question_hash: "qh2", lint_flags: ["correct_longest", "negative_stem"], format: "free", options: null }),
        ],
        { count: 7 },
      ),
    );
    render(<AdminCheckItems />);
    const row = await screen.findByTestId("admin-items-row-i1");
    expect(screen.getByTestId("admin-items-count").textContent).toContain("7 to review — showing the first 2");
    expect(screen.getByTestId("admin-items-reports-i1-wrong_answer").textContent).toBe("Wrong answer ×2");
    expect(screen.getByTestId("admin-items-reports-i1-not_from_my_course").textContent).toBe("Not from my course ×1");
    expect(screen.queryByTestId("admin-items-reports-i1-unclear")).toBeNull();
    expect(within(row).getByText("A. the base case — key")).toBeTruthy();
    expect(within(row).getByText("B. a loop")).toBeTruthy();
    expect(row.textContent).toContain("The base case returns without recursing.");
    expect(screen.getByTestId("admin-items-flag-i2-correct_longest").textContent).toBe("Key is the longest option");
    expect(screen.getByTestId("admin-items-flag-i2-negative_stem").textContent).toBe("Negatively worded");
  });

  it("names what the alignment check changed (spec §13 A119)", async () => {
    api.adminCheckItemQueue.mockResolvedValue(
      queue([entry({ lint_flags: ["rubric_unasked_dropped", "concept_retagged"] })]),
    );
    render(<AdminCheckItems />);
    expect((await screen.findByTestId("admin-items-flag-i1-rubric_unasked_dropped")).textContent).toBe(
      "Criteria the question never asks for were dropped",
    );
    expect(screen.getByTestId("admin-items-flag-i1-concept_retagged").textContent).toBe(
      "Moved to the concept it tests",
    );
  });

  it("approves an item and every row of its course question leaves the queue", async () => {
    api.adminCheckItemQueue.mockResolvedValue(
      queue([entry(), entry({ id: "i1b", concept_key: "base case" }), entry({ id: "i3", question_hash: "qh3" })]),
    );
    api.adminApproveCheckItem.mockResolvedValue({ id: "i1", status: "approved", restored: false });
    render(<AdminCheckItems />);
    fireEvent.click(await screen.findByTestId("admin-items-approve-i1"));
    await waitFor(() => expect(screen.queryByTestId("admin-items-row-i1")).toBeNull());
    expect(api.adminApproveCheckItem).toHaveBeenCalledWith("i1");
    expect(screen.queryByTestId("admin-items-row-i1b")).toBeNull(); // the same question, another concept
    expect(screen.getByTestId("admin-items-row-i3")).toBeTruthy();
    expect(screen.getByTestId("admin-items-count").textContent).toContain("1 to review");
    expect(toast.success).toHaveBeenCalled();
  });

  it("retires only on the second click", async () => {
    api.adminCheckItemQueue.mockResolvedValue(queue([entry()]));
    api.adminRetireCheckItem.mockResolvedValue({ id: "i1", status: "retired", items: 1, students: 3, voided: 4 });
    render(<AdminCheckItems />);
    const retire = await screen.findByTestId("admin-items-retire-i1");
    fireEvent.click(retire);
    expect(api.adminRetireCheckItem).not.toHaveBeenCalled();
    expect(retire.textContent).toContain("Click again to retire and void its results");
    fireEvent.click(retire);
    await waitFor(() => expect(api.adminRetireCheckItem).toHaveBeenCalledWith("i1"));
    expect(await screen.findByTestId("admin-items-empty")).toBeTruthy();
    expect(toast.success).toHaveBeenCalledWith("Retired for the whole course — results from 3 students voided.");
  });

  it("marks a quarantined item and says an approval restores it (spec §13 A123)", async () => {
    api.adminCheckItemQueue.mockResolvedValue(queue([entry({ quarantined: true, status: "quarantined" })]));
    api.adminApproveCheckItem.mockResolvedValue({ id: "i1", status: "approved", restored: true });
    render(<AdminCheckItems />);
    expect((await screen.findByTestId("admin-items-quarantined-i1")).textContent).toContain(
      "hidden from students until you decide",
    );
    expect(screen.getByTestId("admin-items-count").textContent).toContain(
      "Reports from 2 different students hide a question from everyone",
    );
    const approve = screen.getByTestId("admin-items-approve-i1");
    expect(approve.textContent).toBe("Approve and restore");
    fireEvent.click(approve);
    await waitFor(() => expect(api.adminApproveCheckItem).toHaveBeenCalledWith("i1"));
    expect(toast.success).toHaveBeenCalledWith("Approved — restored for students, and it leaves the queue.");
  });

  it("keeps the row and toasts when an action fails", async () => {
    api.adminCheckItemQueue.mockResolvedValue(queue([entry()]));
    api.adminApproveCheckItem.mockRejectedValue(new Error("409 retired"));
    render(<AdminCheckItems />);
    fireEvent.click(await screen.findByTestId("admin-items-approve-i1"));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.getByTestId("admin-items-row-i1")).toBeTruthy();
  });

  it("offers a retry when the queue cannot be read", async () => {
    api.adminCheckItemQueue.mockRejectedValueOnce(new Error("down")).mockResolvedValueOnce(queue([]));
    render(<AdminCheckItems />);
    fireEvent.click(await screen.findByTestId("admin-items-retry"));
    expect(await screen.findByTestId("admin-items-empty")).toBeTruthy();
    expect(api.adminCheckItemQueue).toHaveBeenCalledTimes(2);
  });

  it("an unfinished retire can only be retired again", async () => {
    api.adminCheckItemQueue.mockResolvedValue(queue([entry({ retire_pending: true, status: "retired" })]));
    render(<AdminCheckItems />);
    expect(await screen.findByTestId("admin-items-retire-i1")).toBeTruthy();
    expect(screen.queryByTestId("admin-items-approve-i1")).toBeNull();
    expect(screen.getByTestId("admin-items-row-i1").textContent).toContain("Retire not finished");
  });
});
