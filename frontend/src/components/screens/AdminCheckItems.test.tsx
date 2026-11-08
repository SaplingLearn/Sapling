// @vitest-environment jsdom
/**
 * The /admin/check-items review queue (spec §13 A113; GitHub #695).
 *
 * What these pin:
 *   - the admin gate (a non-admin gets the refusal and no request is made);
 *   - each entry shows its lint flags, its reports by reason, the question with
 *     its key marked, the final answer and the reference;
 *   - Approve calls the API and every row of that course question leaves;
 *   - Retire takes two clicks (it withdraws the question course-wide);
 *   - a failed action keeps the row and toasts; a failed load offers a retry;
 *   - nothing to review says so; a retire-pending item cannot be approved;
 *   - spec §13 A124: a held item says it is served to no one, the key-hold
 *     codes are named, a numeric item shows its key value and tolerance, and
 *     the Key audit tab draws a course's sample, shows the key-error rate with
 *     its 95% interval and records a verdict (then re-reads the sample).
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
  adminCheckItemAuditSample: vi.fn(),
  adminAuditCheckItem: vi.fn(),
}));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), ...api }));

import type {
  AdminAuditItem,
  AdminAuditSample,
  AdminCheckItemEntry,
  AdminCheckItemQueue,
  AuditCounts,
} from "@/lib/api";
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
  held: false,
  prompt: "Which case stops the recursion?",
  options: [
    { letter: "A", text: "the base case", correct: true },
    { letter: "B", text: "a loop", correct: false },
  ],
  final_answer: "the base case",
  reference_answer: "The base case returns without recursing. Final answer: the base case.",
  canonical_answer: null,
  tolerance: null,
  ...over,
});

const counts = (over: Partial<AuditCounts> = {}): AuditCounts => ({
  audited: 0, correct: 0, wrong: 0, ambiguous: 0,
  key_error: { rate: null, ci_low: null, ci_high: null },
  key_error_or_ambiguous: { rate: null, ci_low: null, ci_high: null },
  ...over,
});

const auditItem = (over: Partial<AdminAuditItem> = {}): AdminAuditItem => ({
  id: "a1",
  course_id: "c1",
  concept_key: "load factor",
  question_hash: "qa1",
  format: "free",
  difficulty: 2,
  key_status: "verified",
  verdict: null,
  audited_at: null,
  prompt: "A table holds 4 entries in 5 buckets. What is its load factor?",
  options: null,
  final_answer: "0.8",
  reference_answer: "Entries over buckets: 4 / 5. Final answer: 0.8.",
  canonical_answer: "0.8",
  tolerance: 0.01,
  ...over,
});

const auditSample = (items: AdminAuditItem[], summary: Partial<AuditCounts> = {}): AdminAuditSample => ({
  course_id: "c1",
  seed: "c1",
  population: 40,
  items,
  summary: {
    ...counts(summary),
    by_key_status: { verified: counts(), held: counts(), unverified: counts() },
  },
});

const queue = (items: AdminCheckItemEntry[], over: Partial<AdminCheckItemQueue> = {}): AdminCheckItemQueue => ({
  items, count: items.length, page_size: 100, retire_min_reporters: 2, ...over,
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
    api.adminApproveCheckItem.mockResolvedValue({ id: "i1", status: "approved" });
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
    api.adminRetireCheckItem.mockResolvedValue({ id: "i1", status: "retired", items: 1 });
    render(<AdminCheckItems />);
    const retire = await screen.findByTestId("admin-items-retire-i1");
    fireEvent.click(retire);
    expect(api.adminRetireCheckItem).not.toHaveBeenCalled();
    expect(retire.textContent).toContain("Click again");
    fireEvent.click(retire);
    await waitFor(() => expect(api.adminRetireCheckItem).toHaveBeenCalledWith("i1"));
    expect(await screen.findByTestId("admin-items-empty")).toBeTruthy();
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

  it("a held item says it is served to no one and names its key hold (spec §13 A124)", async () => {
    api.adminCheckItemQueue.mockResolvedValue(
      queue([
        entry({ held: true, lint_flags: ["key_disputed"] }),
        entry({
          id: "i2", question_hash: "qh2", format: "free", options: null,
          lint_flags: ["key_unsolved", "key_audit_wrong", "key_audit_ambiguous"],
          final_answer: "0.8", canonical_answer: "0.8", tolerance: 0.05,
        }),
      ]),
    );
    render(<AdminCheckItems />);
    expect((await screen.findByTestId("admin-items-held-i1")).textContent).toContain("served to no one");
    expect(screen.queryByTestId("admin-items-held-i2")).toBeNull(); // confirmed since: no longer held
    expect(screen.getByTestId("admin-items-flag-i1-key_disputed").textContent).toBe(
      "An independent solve gave a different answer",
    );
    expect(screen.getByTestId("admin-items-flag-i2-key_unsolved").textContent).toBe(
      "An independent solve found the passages don't settle it",
    );
    expect(screen.getByTestId("admin-items-flag-i2-key_audit_wrong").textContent).toBe("An audit found the key wrong");
    expect(screen.getByTestId("admin-items-flag-i2-key_audit_ambiguous").textContent).toBe(
      "An audit found the question ambiguous",
    );
    expect(screen.getByTestId("admin-items-row-i2").textContent).toContain("Numeric key 0.8 ± 0.05");
  });

  it("approving confirms the key", async () => {
    api.adminCheckItemQueue.mockResolvedValue(queue([entry({ held: true, lint_flags: ["key_disputed"] })]));
    api.adminApproveCheckItem.mockResolvedValue({ id: "i1", status: "approved" });
    render(<AdminCheckItems />);
    fireEvent.click(await screen.findByTestId("admin-items-approve-i1"));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("key is confirmed")));
  });
});

describe("AdminCheckItems — key audit (spec §13 A124)", () => {
  const openAudit = async () => {
    api.adminCheckItemQueue.mockResolvedValue(queue([]));
    render(<AdminCheckItems />);
    await screen.findByTestId("admin-items-empty");
    fireEvent.click(screen.getByTestId("admin-items-tab-audit"));
  };

  it("draws a course's sample and shows the key-error rate with its interval", async () => {
    api.adminCheckItemAuditSample.mockResolvedValue(
      auditSample(
        [auditItem(), auditItem({ id: "a2", question_hash: "qa2", key_status: "held", verdict: "wrong" })],
        {
          audited: 30, correct: 26, wrong: 3, ambiguous: 1,
          key_error: { rate: 0.1, ci_low: 0.0346, ci_high: 0.2562 },
          key_error_or_ambiguous: { rate: 0.1333, ci_low: 0.05, ci_high: 0.3 },
        },
      ),
    );
    await openAudit();
    expect((screen.getByTestId("admin-audit-draw") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByTestId("admin-audit-course"), { target: { value: " c1 " } });
    fireEvent.click(screen.getByTestId("admin-audit-draw"));
    const summary = await screen.findByTestId("admin-audit-summary");
    expect(api.adminCheckItemAuditSample).toHaveBeenCalledWith("c1");
    expect(summary.textContent).toContain("30 audited · key-error rate 10% (95% CI 3.5%–25.6%)");
    expect(summary.textContent).toContain("wrong or ambiguous 13.3%");
    expect(summary.textContent).toContain("2 of 40 stored questions sampled");
    expect(screen.getByTestId("admin-audit-status-a1").textContent).toBe("Key verified");
    expect(screen.getByTestId("admin-audit-status-a2").textContent).toBe("Key held");
    expect(screen.getByTestId("admin-audit-wrong-a2").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("admin-audit-correct-a2").getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByTestId("admin-audit-row-a1").textContent).toContain("Numeric key 0.8 ± 0.01");
  });

  it("records a verdict, then re-reads the sample for the new rate", async () => {
    api.adminCheckItemAuditSample
      .mockResolvedValueOnce(auditSample([auditItem()]))
      .mockResolvedValueOnce(
        auditSample([auditItem({ verdict: "wrong", key_status: "verified" })], {
          audited: 1, wrong: 1, key_error: { rate: 1, ci_low: 0.2065, ci_high: 1 },
        }),
      );
    api.adminAuditCheckItem.mockResolvedValue({ id: "a1", verdict: "wrong", key_status: "verified", held: true });
    await openAudit();
    fireEvent.change(screen.getByTestId("admin-audit-course"), { target: { value: "c1" } });
    fireEvent.click(screen.getByTestId("admin-audit-draw"));
    fireEvent.click(await screen.findByTestId("admin-audit-wrong-a1"));
    await waitFor(() => expect(api.adminAuditCheckItem).toHaveBeenCalledWith("a1", "wrong"));
    await waitFor(() => expect(screen.getByTestId("admin-audit-summary").textContent).toContain("1 audited"));
    expect(api.adminCheckItemAuditSample).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("admin-audit-wrong-a1").getAttribute("aria-pressed")).toBe("true");
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("held"));
  });

  it("a failed draw offers a retry; a failed verdict toasts", async () => {
    api.adminCheckItemAuditSample
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce(auditSample([auditItem()]));
    api.adminAuditCheckItem.mockRejectedValue(new Error("503"));
    await openAudit();
    fireEvent.change(screen.getByTestId("admin-audit-course"), { target: { value: "c1" } });
    fireEvent.click(screen.getByTestId("admin-audit-draw"));
    fireEvent.click(await screen.findByTestId("admin-audit-retry"));
    fireEvent.click(await screen.findByTestId("admin-audit-correct-a1"));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(api.adminCheckItemAuditSample).toHaveBeenCalledTimes(2);
  });
});
