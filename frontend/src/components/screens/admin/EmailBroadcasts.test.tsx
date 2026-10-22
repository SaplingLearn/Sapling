// @vitest-environment jsdom
/**
 * The admin "Email" tab (`EmailBroadcastsTab` in ./EmailBroadcasts).
 *
 * What's pinned here:
 *   - audiences render as radio options with their counts;
 *   - "Send to N people" stays disabled until subject + body + a non-empty
 *     audience are set;
 *   - the real send sits behind a typed confirmation (N or "SEND");
 *   - the preview escapes markup and linkifies URLs (React elements only);
 *   - the not-configured banner follows `/email/status`;
 *   - history polls every 5s while a broadcast is `sending`, and stops once
 *     none are.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  adminEmailStatus: vi.fn(),
  adminEmailAudiences: vi.fn(),
  adminListBroadcasts: vi.fn(),
  adminSendTestBroadcast: vi.fn(),
  adminSendBroadcast: vi.fn(),
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

import { EmailBroadcastsTab, POLL_MS } from "./EmailBroadcasts";

const AUDIENCES = [
  { key: "waitlist_all", label: "Everyone on the waitlist", count: 12 },
  { key: "waitlist_pending", label: "Waitlist, not yet approved", count: 0 },
  { key: "users_all", label: "All users", count: 3 },
];

const broadcast = (over: Record<string, unknown> = {}) => ({
  id: "b1", subject: "Hello", audience: "users_all", status: "sent",
  recipient_count: 3, sent_count: 3, skipped_count: 0, failed_count: 0,
  created_at: "2026-10-20T10:00:00Z", sent_at: "2026-10-20T10:01:00Z", created_by: "admin-1",
  ...over,
});

const fill = (subject: string, body: string) => {
  fireEvent.change(screen.getByTestId("email-subject"), { target: { value: subject } });
  fireEvent.change(screen.getByTestId("email-body"), { target: { value: body } });
};

describe("EmailBroadcastsTab", () => {
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
  });

  it("renders each audience as a radio option with its count", async () => {
    render(<EmailBroadcastsTab />);
    const opt = await screen.findByTestId("email-audience-waitlist_all");
    expect(opt.getAttribute("type")).toBe("radio");
    const label = opt.closest("label")!;
    expect(label.textContent).toContain("Everyone on the waitlist");
    expect(label.textContent).toContain("12");
    expect(screen.getByTestId("email-audience-users_all").closest("label")!.textContent).toContain("3");
  });

  it("keeps Send disabled until subject, body and a non-empty audience are set", async () => {
    render(<EmailBroadcastsTab />);
    const send = (await screen.findByTestId("email-send")) as HTMLButtonElement;
    expect(send.disabled).toBe(true);

    fireEvent.change(screen.getByTestId("email-subject"), { target: { value: "News" } });
    expect(send.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("email-body"), { target: { value: "Body" } });
    expect(send.disabled).toBe(true); // no audience yet

    fireEvent.click(screen.getByTestId("email-audience-waitlist_pending")); // count 0
    expect(send.disabled).toBe(true);

    fireEvent.click(screen.getByTestId("email-audience-waitlist_all"));
    expect(send.disabled).toBe(false);
    expect(send.textContent).toBe("Send to 12 people");

    fireEvent.change(screen.getByTestId("email-body"), { target: { value: "   " } });
    expect(send.disabled).toBe(true);
  });

  it("gates the real send behind typing N (or SEND)", async () => {
    api.adminSendBroadcast.mockResolvedValue({ broadcast: broadcast({ id: "b9", status: "sent", subject: "News" }) });
    render(<EmailBroadcastsTab />);
    await screen.findByTestId("email-audience-waitlist_all");
    fill("News", "Hello there");
    fireEvent.click(screen.getByTestId("email-audience-waitlist_all"));
    fireEvent.click(screen.getByTestId("email-send"));

    const confirm = (await screen.findByTestId("email-send-confirm")) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    const input = screen.getByTestId("email-send-confirm-input");

    fireEvent.change(input, { target: { value: "11" } });
    expect(confirm.disabled).toBe(true);
    fireEvent.click(confirm);
    expect(api.adminSendBroadcast).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "SEND" } });
    expect(confirm.disabled).toBe(false);
    fireEvent.change(input, { target: { value: "12" } });
    expect(confirm.disabled).toBe(false);

    fireEvent.click(confirm);
    await waitFor(() =>
      expect(api.adminSendBroadcast).toHaveBeenCalledWith({ subject: "News", body: "Hello there", audience: "waitlist_all" }),
    );
    await waitFor(() => expect(screen.queryByTestId("email-send-confirm")).toBeNull());
    expect(toastSpies.success).toHaveBeenCalled();
    expect(await screen.findByTestId("email-history-row-b9")).toBeTruthy();
  });

  it("sends a test to the admin and toasts the recipient + status", async () => {
    api.adminSendTestBroadcast.mockResolvedValue({ status: "sent", to: "admin@bu.edu" });
    render(<EmailBroadcastsTab />);
    await screen.findByTestId("email-send-test");
    fill("Subj", "Body");
    fireEvent.click(screen.getByTestId("email-send-test"));
    await waitFor(() => expect(api.adminSendTestBroadcast).toHaveBeenCalledWith({ subject: "Subj", body: "Body" }));
    await waitFor(() => expect(toastSpies.success).toHaveBeenCalledWith(expect.stringContaining("admin@bu.edu")));
    expect(toastSpies.success.mock.calls[0][0]).toContain("sent");
  });

  it("escapes markup and linkifies URLs in the preview", async () => {
    render(<EmailBroadcastsTab />);
    await screen.findByTestId("email-body");
    fill("Hi", "<script>alert(1)</script> <b>bold</b>\n\nVisit https://example.com/path?x=1. Thanks!\nsecond line");

    const preview = screen.getByTestId("email-preview");
    expect(preview.querySelector("script")).toBeNull();
    expect(preview.querySelector("b")).toBeNull();
    expect(preview.textContent).toContain("<script>alert(1)</script>");

    const paras = preview.querySelectorAll("p");
    expect(paras).toHaveLength(2);
    const link = preview.querySelector("a")!;
    expect(link.getAttribute("href")).toBe("https://example.com/path?x=1"); // trailing "." stripped
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(paras[1].querySelectorAll("br")).toHaveLength(1);
    expect(paras[1].textContent).toContain(". Thanks!");

    // A closing paren the URL opened stays; the sentence's own paren is trimmed.
    fill("Hi", "(see https://en.wikipedia.org/wiki/Foo_(bar))");
    expect(screen.getByTestId("email-preview").querySelector("a")!.getAttribute("href"))
      .toBe("https://en.wikipedia.org/wiki/Foo_(bar)");
  });

  it("shows the not-configured banner only when email isn't configured", async () => {
    api.adminEmailStatus.mockResolvedValue({ configured: false, from_address: "" });
    render(<EmailBroadcastsTab />);
    expect(await screen.findByTestId("email-not-configured-banner")).toBeTruthy();
    cleanup();

    api.adminEmailStatus.mockResolvedValue({ configured: true, from_address: "x@y.z" });
    render(<EmailBroadcastsTab />);
    await screen.findByTestId("email-send");
    expect(screen.queryByTestId("email-not-configured-banner")).toBeNull();
  });

  it("polls history every 5s while a broadcast is sending, then stops", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    api.adminListBroadcasts
      .mockResolvedValueOnce({ broadcasts: [broadcast({ status: "sending", sent_count: 1 })] })
      .mockResolvedValueOnce({ broadcasts: [broadcast({ status: "sending", sent_count: 2 })] })
      .mockResolvedValue({ broadcasts: [broadcast({ status: "sent" })] });

    render(<EmailBroadcastsTab />);
    expect((await screen.findByTestId("email-history-status-b1")).textContent).toBe("sending");
    expect(api.adminListBroadcasts).toHaveBeenCalledTimes(1);

    await act(async () => { vi.advanceTimersByTime(POLL_MS); });
    expect(api.adminListBroadcasts).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("email-history-status-b1").textContent).toBe("sending");

    await act(async () => { vi.advanceTimersByTime(POLL_MS); });
    expect(api.adminListBroadcasts).toHaveBeenCalledTimes(3);
    await waitFor(() => expect(screen.getByTestId("email-history-status-b1").textContent).toBe("sent"));

    await act(async () => { vi.advanceTimersByTime(POLL_MS * 4); });
    expect(api.adminListBroadcasts).toHaveBeenCalledTimes(3);
  });
});
