// @vitest-environment jsdom
/**
 * Admin → Users → "Account tools" (`AccountToolsDialog`) — the flows the
 * sibling `AccountToolsDialog.test.tsx` leaves unpinned:
 *   - the dialog title / toast name the account by name, else email, else id;
 *   - the meta loading line, and the env badge hiding while a review is open;
 *   - each action's review title and the "Writes to" badge (a pull writes to
 *     THIS env, a push to the peer) with its danger copy;
 *   - the confirm label (email vs user id, blank email → id) and its hint;
 *   - running labels per action; a pull's call, toast, and its re-read on error;
 *   - the size-less confirm labels; a blocked copy with a missing source;
 *   - focus lands on the confirm input, or Back when the copy is blocked;
 *   - a review response arriving after Back is dropped;
 *   - switching to another account resets the review and re-reads meta;
 *   - no majors → "Seed…" disabled; copy buttons' title tooltips.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

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

type User = {
  id: string; name: string; email: string | null; is_approved: boolean;
  last_sign_in_at: string | null; created_at: string; roles: string[];
};

const ADA: User = {
  id: "u-ada", name: "Ada Lovelace", email: "Ada@bu.edu", is_approved: true,
  last_sign_in_at: null, created_at: "2026-10-01T00:00:00Z", roles: [],
};

const BOB: User = { ...ADA, id: "u-bob", name: "Bob", email: "bob@bu.edu" };

const META = {
  env: "production",
  majors: [
    { key: "cs", label: "Computer Science", courses: [{ code: "CAS CS 111", name: "Intro to CS 1" }] },
    { key: "biology", label: "Biology", courses: [{ code: "CAS BI 107", name: "Biology 1" }] },
  ],
  sync: { configured: false, peer_env: null },
};

const SYNCED = { ...META, env: "staging", sync: { configured: true, peer_env: "production" } };

const FULL = {
  exists: true,
  courses: [{ code: "CAS CS 111", name: "Intro to CS 1", term_id: "fall-2026" }],
  counts: { enrollments: 1, notes: 2 },
  total_xp: 10,
  empty: false,
};

const EMPTY = { exists: true, courses: [], counts: {}, total_xp: 0, empty: true };
const XP_ONLY = { exists: true, courses: [], counts: { xp_events: 3 }, total_xp: 1250, empty: false };

const onClose = vi.fn();

beforeEach(() => {
  api.adminAccountsMeta.mockResolvedValue(META);
  api.adminAccountSummary.mockResolvedValue(FULL);
  api.adminCopyPreview.mockResolvedValue({
    direction: "push",
    source: { env: "staging", summary: FULL },
    destination: { env: "production", summary: FULL },
  });
  api.adminSeedAccount.mockResolvedValue({ major: "cs", wiped: {}, created: { notes: 1 } });
  api.adminWipeAccount.mockResolvedValue({ wiped: { notes: 1 } });
  api.adminCopyAccount.mockResolvedValue({ direction: "push", peer_env: "production", counts: { notes: 1 } });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const open = async (user: User = ADA) => {
  const utils = render(<AccountToolsDialog user={user} onClose={onClose} />);
  await screen.findByTestId("admin-account-env-badge");
  return utils;
};

const btn = (id: string) => screen.getByTestId(id) as HTMLButtonElement;

const confirm = (text: string) =>
  fireEvent.change(screen.getByTestId("admin-account-confirm-input"), { target: { value: text } });

const review = async (id: string) => {
  fireEvent.click(btn(id));
  await screen.findByTestId("admin-account-review-confirm");
};

const reviewTitle = () =>
  screen.getByTestId("admin-account-review").querySelector("h3")?.textContent;

const deferred = <T,>() => {
  let resolve: (v: T) => void = () => {};
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
};

describe("AccountToolsDialog flows", () => {
  it("names the account by name, else email, else id", async () => {
    await open();
    expect(screen.getByText("Account tools: Ada Lovelace")).toBeTruthy();
    cleanup();

    await open({ ...ADA, name: "" });
    expect(screen.getByText("Account tools: Ada@bu.edu")).toBeTruthy();
    cleanup();

    await open({ ...ADA, name: "", email: null });
    expect(screen.getByText("Account tools: u-ada")).toBeTruthy();
    await review("admin-account-wipe");
    confirm("U-ADA");
    fireEvent.click(btn("admin-account-review-confirm"));
    await waitFor(() => expect(toastSpies.success).toHaveBeenCalledWith("Wiped u-ada's data: removed 1 row."));
  });

  it("shows the meta loading line, and hides the env badge while reviewing", async () => {
    const meta = deferred<typeof META>();
    api.adminAccountsMeta.mockReturnValue(meta.promise);
    render(<AccountToolsDialog user={ADA} onClose={onClose} />);
    expect(screen.getByTestId("admin-account-meta-loading").textContent).toBe("Loading environment…");
    expect(btn("admin-account-wipe").disabled).toBe(true);
    expect(btn("admin-account-seed").textContent).toBe("Seed…");
    expect(screen.queryByTestId("admin-account-copy-unconfigured")).toBeNull();

    await act(async () => { meta.resolve(META); });
    expect(screen.queryByTestId("admin-account-meta-loading")).toBeNull();
    expect(screen.getByTestId("admin-account-env")).toBeTruthy();

    await review("admin-account-wipe");
    expect(screen.queryByTestId("admin-account-env")).toBeNull();
    expect(screen.queryByTestId("admin-account-meta-loading")).toBeNull();
    expect(screen.queryByTestId("admin-account-wipe")).toBeNull();
  });

  it("titles each review and names the environment it writes to", async () => {
    await open();
    await review("admin-account-seed");
    expect(reviewTitle()).toBe("Review: seed Computer Science");
    const target = screen.getByTestId("admin-account-review-target");
    expect(target.getAttribute("data-env")).toBe("production");
    expect(target.textContent).toContain("Writes to");
    expect(target.textContent).toContain(
      "Production. Live student data will be deleted and can't be restored.",
    );
    fireEvent.click(btn("admin-account-review-back"));

    await review("admin-account-wipe");
    expect(reviewTitle()).toBe("Review: wipe study data");
    cleanup();

    api.adminAccountsMeta.mockResolvedValue(SYNCED);
    await open();
    await review("admin-account-copy-push");
    expect(reviewTitle()).toBe("Review: copy to production");
    expect(screen.getByTestId("admin-account-review-target").getAttribute("data-env")).toBe("production");
    fireEvent.click(btn("admin-account-review-back"));

    await review("admin-account-copy-pull");
    expect(reviewTitle()).toBe("Review: copy from production");
    const pullTarget = screen.getByTestId("admin-account-review-target");
    expect(pullTarget.getAttribute("data-env")).toBe("staging");
    expect(screen.getByTestId("admin-account-review-target-badge").textContent).toBe("STAGING");
    expect(pullTarget.textContent).toContain("This deletes data on staging. It can't be undone.");
  });

  it("asks for the email, or the user id for a blank/undecryptable email, with a hint", async () => {
    await open();
    await review("admin-account-wipe");
    const label = screen.getByTestId("admin-account-confirm-input").closest("label")!;
    expect(label.textContent).toContain("Type the account's email Ada@bu.edu to confirm");
    expect(label.textContent).toContain("Not case-sensitive.");
    confirm("ada@bu.edu");
    expect(label.textContent).toContain("Confirmed. The button below runs it.");
    expect(btn("admin-account-review-confirm").disabled).toBe(false);
    confirm("u-ada");
    expect(btn("admin-account-review-confirm").disabled).toBe(true);
    cleanup();

    await open({ ...ADA, email: "   " });
    await review("admin-account-wipe");
    const idLabel = screen.getByTestId("admin-account-confirm-input").closest("label")!;
    expect(idLabel.textContent).toContain("Type the account's user id u-ada to confirm");
    confirm("   ");
    expect(btn("admin-account-review-confirm").disabled).toBe(true);
    confirm(" u-ada ");
    expect(btn("admin-account-review-confirm").disabled).toBe(false);
  });

  it("labels the running button per action", async () => {
    const seed = deferred<unknown>();
    api.adminSeedAccount.mockReturnValue(seed.promise);
    await open();
    await review("admin-account-seed");
    confirm("ada@bu.edu");
    fireEvent.click(btn("admin-account-review-confirm"));
    await waitFor(() => expect(btn("admin-account-review-confirm").textContent).toBe("Seeding…"));
    expect(api.adminSeedAccount).toHaveBeenCalledWith("u-ada", "cs");
    await act(async () => { seed.resolve({ major: "cs", wiped: {}, created: { notes: 1 } }); });
    expect(toastSpies.success).toHaveBeenCalledWith(
      "Seeded Ada Lovelace with Computer Science: created 1 row, replaced 0 rows.",
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("pulls: calls the copy with pull, says 'Copying…', toasts 'from', and re-reads the pull preview on error", async () => {
    api.adminAccountsMeta.mockResolvedValue(SYNCED);
    const copy = deferred<unknown>();
    api.adminCopyAccount.mockReturnValueOnce(copy.promise);
    await open();
    await review("admin-account-copy-pull");
    confirm("ada@bu.edu");
    fireEvent.click(btn("admin-account-review-confirm"));
    await waitFor(() => expect(btn("admin-account-review-confirm").textContent).toBe("Copying…"));
    expect(api.adminCopyAccount).toHaveBeenCalledWith("u-ada", "pull");
    await act(async () => {
      copy.resolve({ direction: "pull", peer_env: "production", counts: { notes: 2, sessions: 1 } });
    });
    expect(toastSpies.success).toHaveBeenCalledWith("Copied Ada Lovelace from production: 3 rows.");
    expect(onClose).toHaveBeenCalledTimes(1);
    cleanup();

    api.adminCopyAccount.mockRejectedValueOnce(new Error("boom"));
    await open();
    await review("admin-account-copy-pull");
    expect(api.adminCopyPreview).toHaveBeenLastCalledWith("u-ada", "pull");
    const previews = api.adminCopyPreview.mock.calls.length;
    confirm("ada@bu.edu");
    fireEvent.click(btn("admin-account-review-confirm"));
    await waitFor(() => expect(toastSpies.error).toHaveBeenCalledWith("That didn't go through. Try again."));
    await waitFor(() => expect(api.adminCopyPreview.mock.calls.length).toBe(previews + 1));
    expect(api.adminCopyPreview).toHaveBeenLastCalledWith("u-ada", "pull");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("labels the confirm without a size when there is nothing countable", async () => {
    api.adminAccountSummary.mockResolvedValue(EMPTY);
    await open();
    await review("admin-account-wipe");
    expect(btn("admin-account-review-confirm").textContent).toBe("Wipe data");
    fireEvent.click(btn("admin-account-review-back"));

    api.adminAccountSummary.mockResolvedValue(XP_ONLY);
    await review("admin-account-wipe");
    expect(btn("admin-account-review-confirm").textContent).toBe("Wipe 1,250 XP");
    fireEvent.click(btn("admin-account-review-back"));
    await review("admin-account-seed");
    expect(btn("admin-account-review-confirm").textContent).toBe("Delete 1,250 XP and seed Computer Science");
    cleanup();

    api.adminAccountsMeta.mockResolvedValue(SYNCED);
    api.adminCopyPreview.mockResolvedValue({
      direction: "push",
      source: { env: "staging", summary: FULL },
      destination: { env: "production", summary: EMPTY },
    });
    await open();
    await review("admin-account-copy-push");
    expect(btn("admin-account-review-confirm").textContent).toBe("Overwrite production with staging's data");
    expect(screen.getByTestId("admin-account-review-destination-empty").textContent).toBe(
      "Nothing yet on production — nothing will be deleted.",
    );
  });

  it("blocks a copy whose source account doesn't exist and focuses Back", async () => {
    api.adminAccountsMeta.mockResolvedValue(SYNCED);
    api.adminCopyPreview.mockResolvedValue({
      direction: "push",
      source: { env: "staging", summary: { ...EMPTY, exists: false } },
      destination: { env: "production", summary: FULL },
    });
    await open();
    await review("admin-account-copy-push");
    expect(screen.getByTestId("admin-account-review-missing").textContent).toBe(
      "This account hasn't signed in on staging yet, so there's nothing to copy from it.",
    );
    expect(btn("admin-account-review-confirm").disabled).toBe(true);
    expect(screen.queryByTestId("admin-account-confirm-input")).toBeNull();
    expect(document.activeElement).toBe(btn("admin-account-review-back"));
  });

  it("focuses the confirm input once the review is ready", async () => {
    await open();
    await review("admin-account-wipe");
    expect(document.activeElement).toBe(screen.getByTestId("admin-account-confirm-input"));
  });

  it("drops a review response that lands after Back", async () => {
    const summary = deferred<typeof FULL>();
    api.adminAccountSummary.mockReturnValueOnce(summary.promise);
    await open();
    fireEvent.click(btn("admin-account-wipe"));
    expect(screen.getByTestId("admin-account-review-loading").textContent).toBe(
      "Counting what this account holds…",
    );
    fireEvent.click(btn("admin-account-review-back"));
    await act(async () => { summary.resolve(FULL); });
    expect(screen.queryByTestId("admin-account-review")).toBeNull();
    expect(btn("admin-account-wipe")).toBeTruthy();

    await review("admin-account-wipe");
    expect(screen.getByTestId("admin-account-review").getAttribute("data-action")).toBe("wipe");
  });

  it("resets the review and re-reads meta when another account is opened", async () => {
    const { rerender } = await open();
    await review("admin-account-wipe");
    confirm("ada@bu.edu");

    rerender(<AccountToolsDialog user={BOB} onClose={onClose} />);
    await screen.findByTestId("admin-account-env-badge");
    expect(api.adminAccountsMeta).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("admin-account-review")).toBeNull();
    expect(screen.getByText("Account tools: Bob")).toBeTruthy();

    await review("admin-account-wipe");
    expect(api.adminAccountSummary).toHaveBeenLastCalledWith("u-bob");
    expect((screen.getByTestId("admin-account-confirm-input") as HTMLInputElement).value).toBe("");
  });

  it("keeps the selected major across a meta re-read when it still exists", async () => {
    const { rerender } = await open();
    fireEvent.change(screen.getByTestId("admin-account-major"), { target: { value: "biology" } });
    rerender(<AccountToolsDialog user={BOB} onClose={onClose} />);
    await waitFor(() => expect(api.adminAccountsMeta).toHaveBeenCalledTimes(2));
    await screen.findByTestId("admin-account-env-badge");
    expect((screen.getByTestId("admin-account-major") as HTMLSelectElement).value).toBe("biology");
  });

  it("disables seeding when there are no majors", async () => {
    api.adminAccountsMeta.mockResolvedValue({ ...META, majors: [] });
    await open();
    expect(btn("admin-account-seed").textContent).toBe("Seed…");
    expect(btn("admin-account-seed").disabled).toBe(true);
    expect((screen.getByTestId("admin-account-major") as HTMLSelectElement).disabled).toBe(true);
    expect(screen.queryByTestId("admin-account-major-courses")).toBeNull();
    expect(btn("admin-account-wipe").disabled).toBe(false);
  });

  it("explains the copy direction in the buttons' tooltips", async () => {
    api.adminAccountsMeta.mockResolvedValue(SYNCED);
    await open();
    expect(btn("admin-account-copy-push").title).toBe(
      "Overwrite production's data for this account with staging's",
    );
    expect(btn("admin-account-copy-pull").title).toBe(
      "Overwrite staging's data for this account with production's",
    );
    expect(btn("admin-account-copy-pull").textContent).toBe("Copy from production…");
  });

  it("closes from the action list's Close button", async () => {
    await open();
    fireEvent.click(btn("admin-account-close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
