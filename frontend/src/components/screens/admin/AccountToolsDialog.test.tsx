// @vitest-environment jsdom
/**
 * Admin → Users → "Account tools" (`AccountToolsDialog`).
 *
 * What's pinned here:
 *   - `/meta` loads on open and the environment badge names it (PRODUCTION
 *     in the danger style), with the selected major's course codes listed;
 *   - the action list never runs anything: Seed / Wipe / Copy open a review
 *     that reads `/summary` (or `/copy-preview`) and calls no mutation;
 *   - the review says what will be deleted in plain words with real counts
 *     ("4 courses, 31 assignments, …, 1,250 XP"), the current course codes,
 *     and what replaces it; an empty account says nothing will be deleted;
 *   - the final button names the action and its size and stays disabled
 *     until the account's email is typed (case-insensitive; the user id for
 *     an undecryptable row); only it calls the mutation, then toasts + closes;
 *   - a copy whose destination (or source) account doesn't exist is blocked;
 *   - Back returns to the action list; a failed summary offers a retry; a
 *     failed action toasts, stays open and re-reads the summary.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const toastSpies = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
}));
vi.mock("../../ToastProvider", () => ({
  useToast: () => toastSpies,
}));

const api = vi.hoisted(() => ({
  adminAccountsMeta: vi.fn(),
  adminAccountSummary: vi.fn(),
  adminCopyPreview: vi.fn(),
  adminSeedAccount: vi.fn(),
  adminWipeAccount: vi.fn(),
  adminCopyAccount: vi.fn(),
}));
vi.mock("@/lib/api", () => api);

import { AccountToolsDialog } from "./AccountToolsDialog";

const ADA = {
  id: "u-ada", name: "Ada Lovelace", email: "Ada@bu.edu", is_approved: true,
  last_sign_in_at: null, created_at: "2026-10-01T00:00:00Z", roles: [],
};

const META = {
  env: "production",
  majors: [
    {
      key: "cs", label: "Computer Science",
      courses: [
        { code: "CAS CS 111", name: "Intro to CS 1" },
        { code: "CAS CS 112", name: "Intro to CS 2" },
        { code: "CAS CS 131", name: "Combinatoric Structures" },
        { code: "CAS MA 123", name: "Calculus I" },
      ],
    },
    {
      key: "biology", label: "Biology",
      courses: [
        { code: "CAS BI 107", name: "Biology 1" },
        { code: "CAS BI 108", name: "Biology 2" },
        { code: "CAS CH 101", name: "General Chemistry" },
        { code: "CAS MA 115", name: "Statistics" },
      ],
    },
  ],
  sync: { configured: false, peer_env: null },
};

const FULL = {
  exists: true,
  courses: [
    { code: "CAS CS 111", name: "Intro to CS 1", term_id: "fall-2026" },
    { code: "CAS MA 123", name: "Calculus I", term_id: "fall-2026" },
  ],
  counts: {
    enrollments: 4, assignments: 31, graph_nodes: 40, notes: 8, documents: 8, flashcards: 33,
    quiz_attempts: 9, sessions: 4, study_guides: 1, xp_events: 57, user_achievements: 0,
  },
  total_xp: 1250,
  empty: false,
};
// 4 + 31 + 40 + 8 + 8 + 33 + 9 + 4 + 1 (xp_events are shown as the XP total)
const FULL_ITEMS = "138 items";
const FULL_SENTENCE =
  "4 courses, 31 assignments, 40 concepts, 8 notes, 8 documents, 33 flashcards, 9 quizzes, " +
  "4 tutor chats, 1 study guide, 1,250 XP";

const EMPTY = {
  exists: true, courses: [],
  counts: { enrollments: 0, notes: 0, xp_events: 0 },
  total_xp: 0, empty: true,
};

const SMALL = {
  exists: true,
  courses: [{ code: "CAS BI 107", name: "Biology 1", term_id: "fall-2026" }],
  counts: { enrollments: 1, notes: 1, quiz_attempts: 1 },
  total_xp: 0,
  empty: false,
};

const onClose = vi.fn();

beforeEach(() => {
  api.adminAccountsMeta.mockResolvedValue(META);
  api.adminAccountSummary.mockResolvedValue(FULL);
  api.adminCopyPreview.mockResolvedValue({
    direction: "push",
    source: { env: "staging", summary: SMALL },
    destination: { env: "production", summary: FULL },
  });
  api.adminSeedAccount.mockResolvedValue({
    major: "biology", wiped: { notes: 2 }, created: { notes: 8, flashcards: 24, documents: 8 },
  });
  api.adminWipeAccount.mockResolvedValue({ wiped: { notes: 8, flashcards: 24 } });
  api.adminCopyAccount.mockResolvedValue({ direction: "push", peer_env: "production", counts: { notes: 3, sessions: 1 } });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const open = async (user: typeof ADA | (Omit<typeof ADA, "email"> & { email: string | null }) = ADA) => {
  render(<AccountToolsDialog user={user} onClose={onClose} />);
  return screen.findByTestId("admin-account-env-badge");
};

const confirm = (text = "ada@BU.edu") =>
  fireEvent.change(screen.getByTestId("admin-account-confirm-input"), { target: { value: text } });

const btn = (id: string) => screen.getByTestId(id) as HTMLButtonElement;

const noMutation = () => {
  expect(api.adminSeedAccount).not.toHaveBeenCalled();
  expect(api.adminWipeAccount).not.toHaveBeenCalled();
  expect(api.adminCopyAccount).not.toHaveBeenCalled();
};

/** Open an action's review and wait for its counts to load. */
const review = async (id: string) => {
  fireEvent.click(btn(id));
  await screen.findByTestId("admin-account-review-confirm");
};

const SYNCED = { ...META, env: "staging", sync: { configured: true, peer_env: "production" } };

describe("AccountToolsDialog", () => {
  it("renders nothing without a user", () => {
    render(<AccountToolsDialog user={null} onClose={onClose} />);
    expect(screen.queryByTestId("admin-account-tools")).toBeNull();
    expect(api.adminAccountsMeta).not.toHaveBeenCalled();
  });

  it("loads meta and shows the environment badge and the selected major's courses", async () => {
    const badge = await open();
    expect(api.adminAccountsMeta).toHaveBeenCalledTimes(1);
    expect(badge.textContent).toBe("PRODUCTION");
    expect(screen.getByTestId("admin-account-env").getAttribute("data-env")).toBe("production");
    expect(screen.getByTestId("admin-account-env").textContent).toMatch(/production database/);

    const courses = screen.getByTestId("admin-account-major-courses");
    expect(courses.textContent).toContain("CAS CS 111");
    expect(courses.querySelectorAll("li")).toHaveLength(4);

    fireEvent.change(screen.getByTestId("admin-account-major"), { target: { value: "biology" } });
    expect(screen.getByTestId("admin-account-major-courses").textContent).toContain("CAS BI 107");
    expect(screen.getByTestId("admin-account-major-courses").textContent).not.toContain("CAS CS 111");
  });

  it("opens a review instead of acting, for every action", async () => {
    api.adminAccountsMeta.mockResolvedValue(SYNCED);
    await open();
    // No email gate on the list: the buttons only open the review.
    for (const id of ["admin-account-seed", "admin-account-wipe", "admin-account-copy-push", "admin-account-copy-pull"]) {
      expect(btn(id).disabled).toBe(false);
    }
    expect(screen.queryByTestId("admin-account-confirm-input")).toBeNull();

    await review("admin-account-seed");
    expect(screen.getByTestId("admin-account-review").getAttribute("data-action")).toBe("seed");
    expect(api.adminAccountSummary).toHaveBeenCalledWith("u-ada");
    fireEvent.click(btn("admin-account-review-back"));

    await review("admin-account-copy-pull");
    expect(api.adminCopyPreview).toHaveBeenCalledWith("u-ada", "pull");
    noMutation();
  });

  it("seed review: what will be deleted in plain words, current courses, and what replaces it", async () => {
    await open();
    fireEvent.change(screen.getByTestId("admin-account-major"), { target: { value: "biology" } });
    await review("admin-account-seed");

    expect(screen.getByTestId("admin-account-review-target-badge").textContent).toBe("PRODUCTION");
    const del = screen.getByTestId("admin-account-review-delete");
    expect(del.textContent).toContain("Will delete from PRODUCTION");
    expect(screen.getByTestId("admin-account-review-delete-counts").textContent).toBe(FULL_SENTENCE);
    const current = screen.getByTestId("admin-account-review-delete-courses");
    expect(current.textContent).toContain("CAS CS 111");
    expect(current.querySelectorAll("li")).toHaveLength(2);

    const add = screen.getByTestId("admin-account-review-add");
    expect(add.textContent).toContain("Biology");
    expect(screen.getByTestId("admin-account-review-add-courses").querySelectorAll("li")).toHaveLength(4);
    expect(btn("admin-account-review-confirm").textContent).toBe(`Delete ${FULL_ITEMS} and seed Biology`);
    noMutation();
  });

  it("pluralizes singular counts", async () => {
    api.adminAccountSummary.mockResolvedValue(SMALL);
    await open();
    await review("admin-account-wipe");
    expect(screen.getByTestId("admin-account-review-delete-counts").textContent).toBe("1 course, 1 note, 1 quiz");
    expect(btn("admin-account-review-confirm").textContent).toBe("Wipe 3 items");
  });

  it("says nothing will be deleted for an empty account", async () => {
    api.adminAccountSummary.mockResolvedValue(EMPTY);
    await open();
    await review("admin-account-seed");
    expect(screen.getByTestId("admin-account-review-delete-empty").textContent).toBe(
      "This account has no study data yet — nothing will be deleted.",
    );
    expect(screen.queryByTestId("admin-account-review-delete-counts")).toBeNull();
    expect(btn("admin-account-review-confirm").textContent).toBe("Seed Computer Science");
  });

  it("gates the final confirm on the typed email, then seeds, toasts and closes", async () => {
    await open();
    fireEvent.change(screen.getByTestId("admin-account-major"), { target: { value: "biology" } });
    await review("admin-account-seed");

    expect(btn("admin-account-review-confirm").disabled).toBe(true);
    confirm("ada@bu.ed");
    expect(btn("admin-account-review-confirm").disabled).toBe(true);
    confirm("  ADA@bu.edu ");
    expect(btn("admin-account-review-confirm").disabled).toBe(false);
    noMutation();

    fireEvent.click(btn("admin-account-review-confirm"));
    await waitFor(() => expect(api.adminSeedAccount).toHaveBeenCalledWith("u-ada", "biology"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(toastSpies.success).toHaveBeenCalledWith(
      "Seeded Ada Lovelace with Biology: created 40 rows, replaced 2 rows.",
    );
  });

  it("confirms an undecryptable account by its user id", async () => {
    await open({ ...ADA, email: null });
    await review("admin-account-wipe");
    confirm("u-ada");
    expect(btn("admin-account-review-confirm").disabled).toBe(false);
  });

  it("wipe review reminds what is kept; confirming wipes, toasts and closes", async () => {
    await open();
    await review("admin-account-wipe");
    expect(screen.getByTestId("admin-account-review-kept").textContent).toMatch(/profile, settings, roles/);
    expect(screen.queryByTestId("admin-account-review-add")).toBeNull();
    expect(btn("admin-account-review-confirm").textContent).toBe(`Wipe ${FULL_ITEMS}`);

    confirm();
    fireEvent.click(btn("admin-account-review-confirm"));
    await waitFor(() => expect(api.adminWipeAccount).toHaveBeenCalledWith("u-ada"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(toastSpies.success).toHaveBeenCalledWith("Wiped Ada Lovelace's data: removed 32 rows.");
  });

  it("Back returns to the action list without acting and forgets the typed email", async () => {
    await open();
    await review("admin-account-wipe");
    confirm();
    fireEvent.click(btn("admin-account-review-back"));

    expect(screen.queryByTestId("admin-account-review")).toBeNull();
    expect(screen.getByTestId("admin-account-env-badge").textContent).toBe("PRODUCTION");
    expect(btn("admin-account-wipe")).toBeTruthy();
    noMutation();

    await review("admin-account-wipe");
    expect((screen.getByTestId("admin-account-confirm-input") as HTMLInputElement).value).toBe("");
  });

  it("copy review shows what the destination has (deleted) beside what replaces it", async () => {
    api.adminAccountsMeta.mockResolvedValue(SYNCED);
    await open();
    expect(btn("admin-account-copy-push").textContent).toBe("Copy to production…");
    await review("admin-account-copy-push");

    expect(api.adminCopyPreview).toHaveBeenCalledWith("u-ada", "push");
    // A push from staging writes to production: the danger badge names it.
    expect(screen.getByTestId("admin-account-review-target").getAttribute("data-env")).toBe("production");
    const dest = screen.getByTestId("admin-account-review-destination");
    expect(dest.textContent).toMatch(/PRODUCTION currently has \(will be deleted\)/);
    expect(screen.getByTestId("admin-account-review-destination-counts").textContent).toBe(FULL_SENTENCE);
    expect(screen.getByTestId("admin-account-review-source").textContent).toMatch(/from STAGING/);
    expect(screen.getByTestId("admin-account-review-source-counts").textContent).toBe("1 course, 1 note, 1 quiz");
    expect(btn("admin-account-review-confirm").textContent).toBe(
      `Overwrite production's ${FULL_ITEMS} with staging's data`,
    );

    confirm();
    fireEvent.click(btn("admin-account-review-confirm"));
    await waitFor(() => expect(api.adminCopyAccount).toHaveBeenCalledWith("u-ada", "push"));
    await waitFor(() => expect(toastSpies.success).toHaveBeenCalledWith("Copied Ada Lovelace to production: 4 rows."));
    expect(onClose).toHaveBeenCalled();
  });

  it("blocks a copy whose destination account doesn't exist", async () => {
    api.adminAccountsMeta.mockResolvedValue(SYNCED);
    api.adminCopyPreview.mockResolvedValue({
      direction: "push",
      source: { env: "staging", summary: SMALL },
      destination: { env: "production", summary: { ...EMPTY, exists: false } },
    });
    await open();
    await review("admin-account-copy-push");

    const missing = screen.getByTestId("admin-account-review-missing");
    expect(missing.textContent).toMatch(/hasn't signed in on production yet/);
    expect(btn("admin-account-review-confirm").disabled).toBe(true);
    expect(screen.queryByTestId("admin-account-confirm-input")).toBeNull();
    noMutation();
  });

  it("shows a retry when the summary fails to load", async () => {
    api.adminAccountSummary.mockRejectedValueOnce(new Error("boom"));
    await open();
    fireEvent.click(btn("admin-account-wipe"));
    await screen.findByTestId("admin-account-review-error");
    expect(screen.queryByTestId("admin-account-review-confirm")).toBeNull();
    expect(screen.queryByTestId("admin-account-confirm-input")).toBeNull();

    fireEvent.click(btn("admin-account-review-retry"));
    expect((await screen.findByTestId("admin-account-review-delete-counts")).textContent).toBe(FULL_SENTENCE);
    expect(api.adminAccountSummary).toHaveBeenCalledTimes(2);
  });

  it("disables everything while the action runs", async () => {
    let resolveWipe: (v: unknown) => void = () => {};
    api.adminWipeAccount.mockReturnValue(new Promise((r) => { resolveWipe = r; }));
    await open();
    await review("admin-account-wipe");
    confirm();
    fireEvent.click(btn("admin-account-review-confirm"));

    await waitFor(() => expect(btn("admin-account-review-confirm").textContent).toBe("Wiping…"));
    expect(btn("admin-account-review-confirm").disabled).toBe(true);
    expect(btn("admin-account-review-back").disabled).toBe(true);
    expect((screen.getByTestId("admin-account-confirm-input") as HTMLInputElement).disabled).toBe(true);
    resolveWipe({ wiped: {} });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("keeps the review open, toasts the backend's sentence and re-reads the summary on error", async () => {
    api.adminWipeAccount.mockRejectedValue(
      Object.assign(new Error('{"detail":"An operation is already running for this account."}'), {
        status: 409,
        body: { detail: "An operation is already running for this account." },
      }),
    );
    await open();
    await review("admin-account-wipe");
    confirm();
    fireEvent.click(btn("admin-account-review-confirm"));

    await waitFor(() =>
      expect(toastSpies.error).toHaveBeenCalledWith("An operation is already running for this account."),
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(toastSpies.success).not.toHaveBeenCalled();
    expect(screen.getByTestId("admin-account-review")).toBeTruthy();
    await waitFor(() => expect(api.adminAccountSummary).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(btn("admin-account-review-confirm").disabled).toBe(false));
  });

  it("shows a muted note instead of copy buttons when sync isn't configured", async () => {
    await open();
    expect(screen.getByTestId("admin-account-copy-unconfigured")).toBeTruthy();
    expect(screen.queryByTestId("admin-account-copy-push")).toBeNull();
    expect(screen.queryByTestId("admin-account-copy-pull")).toBeNull();
  });

  it("disables copy and says so when the peer is unreachable", async () => {
    api.adminAccountsMeta.mockResolvedValue({ ...META, sync: { configured: true, peer_env: null } });
    await open();
    expect(screen.getByTestId("admin-account-copy-unreachable")).toBeTruthy();
    expect(btn("admin-account-copy-push").disabled).toBe(true);
    expect(btn("admin-account-copy-pull").disabled).toBe(true);
    expect(btn("admin-account-wipe").disabled).toBe(false);
  });

  it("shows a retry when meta fails to load", async () => {
    api.adminAccountsMeta.mockRejectedValueOnce(new Error("boom"));
    render(<AccountToolsDialog user={ADA} onClose={onClose} />);
    await screen.findByTestId("admin-account-meta-error");
    expect(btn("admin-account-wipe").disabled).toBe(true);

    fireEvent.click(btn("admin-account-meta-retry"));
    expect((await screen.findByTestId("admin-account-env-badge")).textContent).toBe("PRODUCTION");
  });
});
