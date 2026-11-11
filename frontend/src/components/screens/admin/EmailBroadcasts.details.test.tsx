// @vitest-environment jsdom
/**
 * Characterization of the admin "Email" tab (`EmailBroadcastsTab`) beyond
 * what EmailBroadcasts.test.tsx pins: copy, labels, chip classes, the
 * history cells, the confirm dialog's text and keyboard paths, the failure
 * toasts and the in-flight labels. Written against the pre-split component
 * so the complexity refactor can't drift any of it.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  adminEmailStatus: vi.fn(),
  adminEmailAudiences: vi.fn(),
  adminListBroadcasts: vi.fn(),
  adminSendTestBroadcast: vi.fn(),
  adminSendBroadcast: vi.fn(),
  adminPreviewBroadcast: vi.fn(),
  adminResumeBroadcast: vi.fn(),
}));
vi.mock("@/lib/api", () => api);

const toastSpies = vi.hoisted(() => ({
  show: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warn: vi.fn(),
}));
vi.mock("@/components/ToastProvider", () => ({ useToast: () => toastSpies }));

import { EmailBroadcastsTab, PREVIEW_DEBOUNCE_MS } from "./EmailBroadcasts";

const AUDIENCES = [
  { key: "waitlist_all", label: "Everyone on the waitlist", count: 12 },
  { key: "users_all", label: "All users", count: 1 },
];

const broadcast = (over: Record<string, unknown> = {}) => ({
  id: "b1", subject: "Hello", audience: "users_all", status: "sent",
  recipient_count: 3, sent_count: 3, skipped_count: 0, failed_count: 0,
  created_at: "2026-10-20T10:00:00Z", sent_at: "2026-10-20T10:01:00Z", created_by: "admin-1",
  ...over,
});

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const PREVIEW_WAIT = { timeout: PREVIEW_DEBOUNCE_MS * 6 };
const btn = (id: string) => screen.getByTestId(id) as HTMLButtonElement;

const fill = (subject: string, body: string) => {
  fireEvent.change(screen.getByTestId("email-subject"), { target: { value: subject } });
  fireEvent.change(screen.getByTestId("email-body"), { target: { value: body } });
};

const previewed = (testId = "email-send-test") =>
  waitFor(() => expect(btn(testId).disabled).toBe(false), PREVIEW_WAIT);

/** Draft + audience + preview, then open the confirm dialog. */
async function openConfirm(audienceKey = "waitlist_all") {
  await screen.findByTestId(`email-audience-${audienceKey}`);
  fill("  News  ", "Hello there");
  fireEvent.click(screen.getByTestId(`email-audience-${audienceKey}`));
  await previewed("email-send");
  fireEvent.click(screen.getByTestId("email-send"));
  return (await screen.findByTestId("email-send-confirm-input")) as HTMLInputElement;
}

describe("EmailBroadcastsTab (characterization)", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    Object.values(toastSpies).forEach((f) => f.mockReset());
    api.adminEmailStatus.mockResolvedValue({ configured: true, from_address: "Sapling <hi@sapling.test>" });
    api.adminEmailAudiences.mockResolvedValue({ audiences: AUDIENCES });
    api.adminListBroadcasts.mockResolvedValue({ broadcasts: [] });
    api.adminPreviewBroadcast.mockResolvedValue({ subject: "", html: "<html><body>blank</body></html>" });
  });

  describe("loading and the initial fetch", () => {
    it("shows the skeleton until all three loads settle", async () => {
      const status = deferred<unknown>();
      api.adminEmailStatus.mockReturnValue(status.promise);
      render(<EmailBroadcastsTab />);
      expect(screen.queryByTestId("email-subject")).toBeNull();
      await act(async () => { status.resolve({ configured: true, from_address: "" }); });
      expect(await screen.findByTestId("email-subject")).toBeTruthy();
    });

    it("toasts audience and history load failures, but not a status failure", async () => {
      api.adminEmailStatus.mockRejectedValue(new Error("status down"));
      api.adminEmailAudiences.mockRejectedValue(new Error("aud down"));
      api.adminListBroadcasts.mockRejectedValue(new Error("hist down"));
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-subject");
      expect(toastSpies.error.mock.calls.map((c) => c[0])).toEqual([
        "Couldn't load audiences: Error: aud down",
        "Couldn't load broadcast history: Error: hist down",
      ]);
      expect(screen.queryByTestId("email-not-configured-banner")).toBeNull();
      expect(screen.getByText("No audiences available.")).toBeTruthy();
      expect(screen.getByText("No broadcasts yet.")).toBeTruthy();
      expect(screen.getByTestId("email-history").textContent).toContain("History · 0");
    });

    it("treats missing audiences/broadcasts arrays as empty", async () => {
      api.adminEmailAudiences.mockResolvedValue({});
      api.adminListBroadcasts.mockResolvedValue({});
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-subject");
      expect(screen.getByText("No audiences available.")).toBeTruthy();
      expect(screen.getByText("No broadcasts yet.")).toBeTruthy();
      expect(toastSpies.error).not.toHaveBeenCalled();
    });
  });

  describe("compose", () => {
    it("counts characters against the limits and shows the from address", async () => {
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-subject");
      expect(screen.getByTestId("email-subject-count").textContent).toBe("0/200");
      expect(screen.getByTestId("email-body-count").textContent).toBe("0/20000");
      fill("abc", "hello");
      expect(screen.getByTestId("email-subject-count").textContent).toBe("3/200");
      expect(screen.getByTestId("email-body-count").textContent).toBe("5/20000");
      expect(screen.getByText("From Sapling <hi@sapling.test>")).toBeTruthy();
    });

    it("hides the from line when there is no from address", async () => {
      api.adminEmailStatus.mockResolvedValue({ configured: true, from_address: "" });
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-subject");
      expect(screen.queryByText(/^From /)).toBeNull();
    });

    it("labels Send for zero, one and many recipients", async () => {
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-audience-users_all");
      expect(btn("email-send").textContent).toBe("Send to 0 people");
      fireEvent.click(screen.getByTestId("email-audience-users_all"));
      expect(btn("email-send").textContent).toBe("Send to 1 person");
      fireEvent.click(screen.getByTestId("email-audience-waitlist_all"));
      expect(btn("email-send").textContent).toBe("Send to 12 people");
      expect((screen.getByTestId("email-audience-waitlist_all") as HTMLInputElement).checked).toBe(true);
      expect((screen.getByTestId("email-audience-users_all") as HTMLInputElement).checked).toBe(false);
    });

    it("titles a button variable's chip with its button label", async () => {
      api.adminEmailStatus.mockResolvedValue({
        configured: true, from_address: "x@y.z",
        variables: [{ key: "signin_link", label: "Sign-in link", fallback: "", example: "", button: "Sign in" }],
      });
      render(<EmailBroadcastsTab />);
      const chip = await screen.findByTestId("email-variable-signin_link");
      expect(chip.getAttribute("title")).toBe(
        "{{signin_link}}\nOn its own line it's a \"Sign in\" button. {{signin_link|Your label}} changes the label.",
      );
      expect(chip.className).toBe("chip");
    });
  });

  describe("preview pane", () => {
    it("shows (no subject) for a blank subject, and the typed subject before a preview matches", async () => {
      const pending = deferred<unknown>();
      api.adminPreviewBroadcast.mockReturnValue(pending.promise);
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-subject");
      expect(screen.getByTestId("email-preview-subject").textContent).toBe("(no subject)");
      fill("   ", "");
      expect(screen.getByTestId("email-preview-subject").textContent).toBe("(no subject)");
      fill(" Typed ", "");
      expect(screen.getByTestId("email-preview-subject").textContent).toBe("Typed");
    });

    it("keeps the last good render and notes the failure when a later preview fails", async () => {
      render(<EmailBroadcastsTab />);
      await waitFor(
        () => expect((screen.getByTestId("email-preview-frame") as HTMLIFrameElement).getAttribute("srcdoc")).toContain("blank"),
        PREVIEW_WAIT,
      );
      api.adminPreviewBroadcast.mockRejectedValue(new Error("500"));
      fill("A", "B");
      const err = await screen.findByTestId("email-preview-error", {}, PREVIEW_WAIT);
      expect(err.textContent).toBe("Couldn't load the preview. Showing the last version.");
      expect(err.getAttribute("role")).toBe("status");
      expect(screen.getByTestId("email-preview-frame")).toBeTruthy();
    });
  });

  describe("test send", () => {
    it("shows the in-flight label, then warns on a non-delivered status", async () => {
      const pending = deferred<{ status: string; to: string }>();
      api.adminSendTestBroadcast.mockReturnValue(pending.promise);
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-send-test");
      fill("  Subj ", " Body ");
      await previewed();
      expect(btn("email-send-test").textContent).toBe("Send test to me");
      fireEvent.click(btn("email-send-test"));
      expect(api.adminSendTestBroadcast).toHaveBeenCalledWith({ subject: "Subj", body: "Body" });
      expect(btn("email-send-test").textContent).toBe("Sending test…");
      expect(btn("email-send-test").disabled).toBe(true);
      await act(async () => { pending.resolve({ status: "skipped", to: "me@bu.edu" }); });
      expect(toastSpies.warn).toHaveBeenCalledWith("Test email to me@bu.edu: skipped");
      expect(toastSpies.success).not.toHaveBeenCalled();
      expect(btn("email-send-test").textContent).toBe("Send test to me");
    });

    it("treats queued as success", async () => {
      api.adminSendTestBroadcast.mockResolvedValue({ status: "queued", to: "me@bu.edu" });
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-send-test");
      fill("S", "B");
      await previewed();
      fireEvent.click(btn("email-send-test"));
      await waitFor(() => expect(toastSpies.success).toHaveBeenCalledWith("Test email to me@bu.edu: queued"));
    });

    it("falls back to the error detail for a non-validation failure", async () => {
      api.adminSendTestBroadcast.mockRejectedValue(new Error("boom"));
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-send-test");
      fill("S", "B");
      await previewed();
      fireEvent.click(btn("email-send-test"));
      await waitFor(() => expect(toastSpies.error).toHaveBeenCalledTimes(1));
      expect(toastSpies.error.mock.calls[0][0]).toMatch(/^Test send failed: /);
      await waitFor(() => expect(btn("email-send-test").disabled).toBe(false));
    });
  });

  describe("confirm dialog and the real send", () => {
    it("describes the send, then clears the draft and toasts on success", async () => {
      api.adminSendBroadcast.mockResolvedValue({ broadcast: broadcast({ id: "b9", status: "sending", subject: "News", audience: "waitlist_all" }) });
      render(<EmailBroadcastsTab />);
      const input = await openConfirm();
      expect(screen.getByText("Email 12 people?")).toBeTruthy();
      expect(input.value).toBe("");
      const text = document.querySelector(".flags__confirm-text")!;
      expect(text.textContent).toBe(
        "This sends “News” to 12 people in Everyone on the waitlist. These are real inboxes and it can't be undone.",
      );
      expect(text.querySelector("strong")!.textContent).toBe("Everyone on the waitlist");
      expect(screen.getByText("Type 12 or SEND to confirm")).toBeTruthy();
      expect(btn("email-send-confirm").textContent).toBe("Send to 12 people");

      fireEvent.change(input, { target: { value: " 12 " } });
      fireEvent.click(btn("email-send-confirm"));
      await waitFor(() => expect(screen.queryByTestId("email-send-confirm")).toBeNull());
      expect(toastSpies.success).toHaveBeenCalledWith("Sending to 12 people. Progress shows in History below.");
      expect((screen.getByTestId("email-subject") as HTMLInputElement).value).toBe("");
      expect((screen.getByTestId("email-body") as HTMLTextAreaElement).value).toBe("");
      const row = screen.getByTestId("email-history-row-b9");
      expect(row.textContent).toContain("Everyone on the waitlist");
    });

    it("adds the not-configured note to the confirm text", async () => {
      api.adminEmailStatus.mockResolvedValue({ configured: false, from_address: "" });
      render(<EmailBroadcastsTab />);
      await openConfirm("users_all");
      expect(screen.getByText("Email 1 person?")).toBeTruthy();
      expect(document.querySelector(".flags__confirm-text")!.textContent).toContain(
        " Email isn't configured, so the broadcast will be recorded but nothing is delivered.",
      );
    });

    it("sends on Enter only once the confirmation matches", async () => {
      api.adminSendBroadcast.mockResolvedValue({ broadcast: broadcast({ id: "b9" }) });
      render(<EmailBroadcastsTab />);
      const input = await openConfirm();
      fireEvent.change(input, { target: { value: "nope" } });
      fireEvent.keyDown(input, { key: "Enter" });
      expect(api.adminSendBroadcast).not.toHaveBeenCalled();
      fireEvent.change(input, { target: { value: "SEND" } });
      fireEvent.keyDown(input, { key: "a" });
      expect(api.adminSendBroadcast).not.toHaveBeenCalled();
      fireEvent.keyDown(input, { key: "Enter" });
      await waitFor(() => expect(api.adminSendBroadcast).toHaveBeenCalledTimes(1));
      expect(api.adminSendBroadcast).toHaveBeenCalledWith({ subject: "News", body: "Hello there", audience: "waitlist_all" });
    });

    it("can't be dismissed while the send is in flight, and keeps the draft on failure", async () => {
      const pending = deferred<unknown>();
      api.adminSendBroadcast.mockReturnValue(pending.promise);
      render(<EmailBroadcastsTab />);
      const input = await openConfirm();
      fireEvent.change(input, { target: { value: "SEND" } });
      fireEvent.click(btn("email-send-confirm"));
      expect(btn("email-send-confirm").textContent).toBe("Sending…");
      expect(btn("email-send-confirm").disabled).toBe(true);
      expect(btn("email-send-cancel").disabled).toBe(true);
      expect(btn("email-send").textContent).toBe("Sending…");
      expect(btn("email-send").disabled).toBe(true);

      fireEvent.keyDown(input, { key: "Escape" });
      expect(screen.getByTestId("email-send-confirm")).toBeTruthy();

      await act(async () => { pending.reject(new Error("nope")); });
      expect(toastSpies.error.mock.calls[0][0]).toMatch(/^Send failed: /);
      expect(screen.getByTestId("email-send-confirm")).toBeTruthy();
      expect(btn("email-send-confirm").textContent).toBe("Send to 12 people");
      expect((screen.getByTestId("email-subject") as HTMLInputElement).value).toBe("  News  ");

      fireEvent.keyDown(input, { key: "Escape" });
      await waitFor(() => expect(screen.queryByTestId("email-send-confirm")).toBeNull());
    });

    it("closes on Cancel and starts the next confirmation blank", async () => {
      render(<EmailBroadcastsTab />);
      const input = await openConfirm();
      fireEvent.change(input, { target: { value: "12" } });
      fireEvent.click(btn("email-send-cancel"));
      await waitFor(() => expect(screen.queryByTestId("email-send-confirm")).toBeNull());
      fireEvent.click(btn("email-send"));
      expect(((await screen.findByTestId("email-send-confirm-input")) as HTMLInputElement).value).toBe("");
      expect(api.adminSendBroadcast).not.toHaveBeenCalled();
    });
  });

  describe("history table", () => {
    it("renders headers, cells, chip classes, labels and dates", async () => {
      api.adminListBroadcasts.mockResolvedValue({ broadcasts: [
        broadcast({ id: "a", status: "sent", audience: "users_all" }),
        broadcast({ id: "b", status: "sending", stale: true, audience: "mystery", sent_at: null }),
        broadcast({ id: "c", status: "partial", failed_count: 2, skipped_count: 1, sent_count: 0 }),
        broadcast({ id: "d", status: "failed", failed_count: 3, sent_count: 0 }),
        broadcast({ id: "e", status: "skipped", skipped_count: 3, sent_count: 0 }),
        broadcast({ id: "f", status: "weird" }),
      ] });
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-history-row-a");
      const hist = screen.getByTestId("email-history");
      expect(hist.textContent).toContain("History · 6");
      expect(Array.from(hist.querySelectorAll("th")).map((th) => th.textContent))
        .toEqual(["Subject", "Audience", "Status", "Delivered", "Date"]);

      const cells = (id: string) =>
        Array.from(screen.getByTestId(`email-history-row-${id}`).querySelectorAll("td"));
      const status = (id: string) => screen.getByTestId(`email-history-status-${id}`);

      expect(cells("a")[1].textContent).toBe("All users");
      expect(cells("b")[1].textContent).toBe("mystery");
      expect(cells("a")[3].textContent).toBe("3/3");
      expect(cells("c")[3].textContent).toBe("0/32 failed · 1 skipped");
      expect(cells("d")[3].textContent).toBe("0/33 failed");
      expect(cells("e")[3].textContent).toBe("0/33 skipped");
      expect(cells("a")[4].textContent).toBe(new Date("2026-10-20T10:01:00Z").toLocaleString());
      expect(cells("b")[4].textContent).toBe(new Date("2026-10-20T10:00:00Z").toLocaleString());

      expect(status("a").className).toBe("chip chip--accent");
      expect(status("b").className).toBe("chip chip--info");
      expect(status("b").textContent).toBe("stalled");
      expect(status("c").className).toBe("chip chip--warn");
      expect(status("d").className).toBe("chip chip--warn");
      expect(status("e").className).toBe("chip");
      expect(status("f").className).toBe("chip");
      expect(status("f").textContent).toBe("weird");
    });

    it("labels the resuming row and disables every Resume while one runs", async () => {
      const pending = deferred<unknown>();
      api.adminListBroadcasts.mockResolvedValue({ broadcasts: [
        broadcast({ id: "x", status: "failed", resumable: true, subject: "Ex" }),
        broadcast({ id: "y", status: "partial", resumable: true }),
      ] });
      api.adminResumeBroadcast.mockReturnValue(pending.promise);
      render(<EmailBroadcastsTab />);
      const x = (await screen.findByTestId("email-history-resume-x")) as HTMLButtonElement;
      expect(x.getAttribute("title")).toBe("Send it to everyone in this audience it hasn't reached yet.");
      expect(x.textContent).toBe("Resume");
      fireEvent.click(x);
      expect(x.textContent).toBe("Resuming…");
      expect(x.disabled).toBe(true);
      expect(btn("email-history-resume-y").disabled).toBe(true);
      expect(btn("email-history-resume-y").textContent).toBe("Resume");

      await act(async () => { pending.resolve({ broadcast: broadcast({ id: "x", status: "sent", resumable: false, subject: "Ex" }) }); });
      expect(toastSpies.success).toHaveBeenCalledWith("Resuming “Ex”. Anyone it already reached is skipped.");
      expect(screen.queryByTestId("email-history-resume-x")).toBeNull();
      expect(btn("email-history-resume-y").disabled).toBe(false);
      // The resumed row moves to the top.
      const rows = Array.from(screen.getByTestId("email-history").querySelectorAll("tbody tr"));
      expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual(["email-history-row-x", "email-history-row-y"]);
    });

    it("re-enables Resume after a refused resume", async () => {
      api.adminListBroadcasts.mockResolvedValue({ broadcasts: [broadcast({ id: "x", status: "failed", resumable: true })] });
      api.adminResumeBroadcast.mockRejectedValue(new Error("409"));
      render(<EmailBroadcastsTab />);
      fireEvent.click(await screen.findByTestId("email-history-resume-x"));
      await waitFor(() => expect(toastSpies.error).toHaveBeenCalledTimes(1));
      expect(toastSpies.error.mock.calls[0][0]).toMatch(/^Resume failed: /);
      await waitFor(() => expect(btn("email-history-resume-x").disabled).toBe(false));
      expect(btn("email-history-resume-x").textContent).toBe("Resume");
    });
  });
});
