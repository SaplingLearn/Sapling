// @vitest-environment jsdom
/**
 * The admin "Email" tab (`EmailBroadcastsTab` in ./EmailBroadcasts).
 *
 * What's pinned here:
 *   - audiences render as radio options with their counts;
 *   - "Send to N people" stays disabled until subject + body + a non-empty
 *     audience are set;
 *   - the real send sits behind a typed confirmation (N or "SEND");
 *   - the preview is the server-rendered email: the draft is debounced to
 *     `adminPreviewBroadcast`, its HTML lands in a sandboxed iframe's
 *     srcdoc, stale responses are dropped, and a failure shows inline;
 *   - the not-configured banner follows `/email/status`;
 *   - the "Personalize" chips come from `/email/status` `variables` and insert
 *     `{{key}}` at the caret of the last-focused field (body by default),
 *     within the field's max length; the preview's filled-in subject shows;
 *   - unknown variables on the preview show a warning and disable both sends;
 *     a send's 422 validation message reaches the toast intact;
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
  adminPreviewBroadcast: vi.fn(),
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

import { EmailBroadcastsTab, POLL_MS, PREVIEW_DEBOUNCE_MS, SUBJECT_MAX } from "./EmailBroadcasts";

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

/** A promise the test resolves/rejects by hand, to control response order. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const VARIABLES = [
  { key: "first_name", label: "First name", fallback: "there", example: "Ada" },
  { key: "name", label: "Full name", fallback: "there", example: "Ada Lovelace" },
  { key: "email", label: "Email address", fallback: "", example: "ada@bu.edu" },
];

const PREVIEW_WAIT = { timeout: PREVIEW_DEBOUNCE_MS * 6 };
const frame = () => screen.getByTestId("email-preview-frame") as HTMLIFrameElement;

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
    api.adminPreviewBroadcast.mockResolvedValue({ subject: "", html: "<html><body>blank</body></html>" });
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

  it("debounces the draft into a preview request and shows the HTML in a sandboxed iframe", async () => {
    api.adminPreviewBroadcast.mockImplementation(async ({ subject, body }: { subject: string; body: string }) => ({
      subject, html: `<html><body><h1>${subject}</h1><p>${body}</p></body></html>`,
    }));
    render(<EmailBroadcastsTab />);
    await screen.findByTestId("email-body");
    expect(screen.getByTestId("email-preview").textContent).toContain("Loading preview");

    fill("  News  ", "Hello there\n");
    expect(screen.getByTestId("email-preview-subject").textContent).toBe("News");
    // Not yet: the request waits out the debounce.
    expect(api.adminPreviewBroadcast).not.toHaveBeenCalledWith({ subject: "News", body: "Hello there" });

    await waitFor(
      () => expect(api.adminPreviewBroadcast).toHaveBeenLastCalledWith({ subject: "News", body: "Hello there" }),
      PREVIEW_WAIT,
    );
    await waitFor(() => expect(frame().getAttribute("srcdoc")).toContain("<h1>News</h1>"));

    const f = frame();
    expect(f.getAttribute("title")).toBe("Email preview");
    expect(f.getAttribute("referrerpolicy")).toBe("no-referrer");
    const sandbox = f.getAttribute("sandbox")!.split(/\s+/);
    expect(sandbox).toEqual(expect.arrayContaining(["allow-popups", "allow-popups-to-escape-sandbox"]));
    expect(sandbox).not.toContain("allow-scripts");
    expect(sandbox).not.toContain("allow-same-origin");
  });

  it("ignores an out-of-order preview response and keeps the last HTML while loading", async () => {
    render(<EmailBroadcastsTab />);
    await waitFor(() => expect(frame().getAttribute("srcdoc")).toContain("blank"), PREVIEW_WAIT);

    const first = deferred<{ subject: string; html: string }>();
    const second = deferred<{ subject: string; html: string }>();
    api.adminPreviewBroadcast.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    fill("One", "first");
    await waitFor(
      () => expect(api.adminPreviewBroadcast).toHaveBeenLastCalledWith({ subject: "One", body: "first" }),
      PREVIEW_WAIT,
    );
    fill("Two", "second");
    await waitFor(
      () => expect(api.adminPreviewBroadcast).toHaveBeenLastCalledWith({ subject: "Two", body: "second" }),
      PREVIEW_WAIT,
    );
    // Both still in flight: the previous render stays up (no flash).
    expect(frame().getAttribute("srcdoc")).toContain("blank");

    await act(async () => { second.resolve({ subject: "Two", html: "<p>second</p>" }); });
    expect(frame().getAttribute("srcdoc")).toBe("<p>second</p>");
    await act(async () => { first.resolve({ subject: "One", html: "<p>first</p>" }); });
    expect(frame().getAttribute("srcdoc")).toBe("<p>second</p>");
  });

  it("shows an inline message when the preview fails, without breaking the form", async () => {
    api.adminPreviewBroadcast.mockRejectedValue(new Error("500"));
    render(<EmailBroadcastsTab />);
    await screen.findByTestId("email-body");
    expect((await screen.findByTestId("email-preview-error", {}, PREVIEW_WAIT)).textContent)
      .toContain("Couldn't load the preview.");
    expect(screen.queryByTestId("email-preview-frame")).toBeNull();
    expect(toastSpies.error).not.toHaveBeenCalled();

    // The compose form still works, and a later good preview clears the error.
    api.adminPreviewBroadcast.mockResolvedValue({ subject: "Ok", html: "<p>ok</p>" });
    fill("Ok", "fine");
    expect((screen.getByTestId("email-send-test") as HTMLButtonElement).disabled).toBe(false);
    await waitFor(() => expect(frame().getAttribute("srcdoc")).toBe("<p>ok</p>"), PREVIEW_WAIT);
    expect(screen.queryByTestId("email-preview-error")).toBeNull();
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

  describe("personalization variables", () => {
    beforeEach(() => {
      api.adminEmailStatus.mockResolvedValue({
        configured: true, from_address: "Sapling <hi@sapling.test>", variables: VARIABLES,
      });
    });

    const field = (id: string) => screen.getByTestId(id) as HTMLInputElement | HTMLTextAreaElement;
    const caretAt = (el: HTMLInputElement | HTMLTextAreaElement, start: number, end = start) => {
      act(() => { el.focus(); });
      el.setSelectionRange(start, end);
    };

    it("renders one chip per server variable, with the token and fallback in its tooltip", async () => {
      render(<EmailBroadcastsTab />);
      const row = await screen.findByTestId("email-variables");
      expect(row.textContent).toContain("Personalize:");
      const chips = VARIABLES.map((v) => screen.getByTestId(`email-variable-${v.key}`));
      expect(chips.map((c) => c.textContent)).toEqual(["First name", "Full name", "Email address"]);
      const first = screen.getByTestId("email-variable-first_name");
      expect(first.getAttribute("title")).toContain("{{first_name}}");
      expect(first.getAttribute("title")).toContain("If unknown: there");
      expect(screen.getByTestId("email-variable-email").getAttribute("title")).toBe("{{email}}");
      expect(screen.getByText(/Variables like \{\{first_name\}\} are filled in for each person\./)).toBeTruthy();
    });

    it("hides the chip row when the server sends no variables", async () => {
      api.adminEmailStatus.mockResolvedValue({ configured: true, from_address: "x@y.z" });
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-body");
      expect(screen.queryByTestId("email-variables")).toBeNull();
    });

    it("inserts at the body caret by default, replacing a selection, and keeps the caret after it", async () => {
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-variables");
      fireEvent.change(field("email-body"), { target: { value: "Hi XX, welcome" } });
      // Never focused: the body is the target, at its caret.
      const body = field("email-body");
      body.setSelectionRange(3, 5); // "XX"
      fireEvent.click(screen.getByTestId("email-variable-first_name"));
      expect(body.value).toBe("Hi {{first_name}}, welcome");
      expect(document.activeElement).toBe(body);
      expect(body.selectionStart).toBe(3 + "{{first_name}}".length);
      expect(body.selectionEnd).toBe(body.selectionStart);
      expect(field("email-subject").value).toBe("");
    });

    it("inserts into the subject when the subject was focused last", async () => {
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-variables");
      fireEvent.change(field("email-body"), { target: { value: "Body" } });
      fireEvent.change(field("email-subject"), { target: { value: "Hello !" } });
      caretAt(field("email-subject"), 6);
      fireEvent.click(screen.getByTestId("email-variable-name"));
      const subject = field("email-subject");
      expect(subject.value).toBe("Hello {{name}}!");
      expect(document.activeElement).toBe(subject);
      expect(subject.selectionStart).toBe(6 + "{{name}}".length);
      expect(field("email-body").value).toBe("Body");

      // Focus moves back to the body: the next chip goes there.
      caretAt(field("email-body"), 0);
      fireEvent.click(screen.getByTestId("email-variable-email"));
      expect(field("email-body").value).toBe("{{email}}Body");
      expect(field("email-subject").value).toBe("Hello {{name}}!");
    });

    it("won't insert past the field's max length", async () => {
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-variables");
      const full = "x".repeat(SUBJECT_MAX - 3);
      fireEvent.change(field("email-subject"), { target: { value: full } });
      caretAt(field("email-subject"), full.length);
      fireEvent.click(screen.getByTestId("email-variable-first_name"));
      expect(field("email-subject").value).toBe(full);
      expect(toastSpies.warn).toHaveBeenCalledWith(expect.stringContaining("{{first_name}}"));
    });

    it("shows the preview's filled-in subject once it matches the draft", async () => {
      api.adminPreviewBroadcast.mockImplementation(async ({ subject }: { subject: string }) => ({
        subject: subject.replace("{{first_name}}", "Ada"), html: "<p>ok</p>", unknown_variables: [],
      }));
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-body");
      fill("Hi {{first_name}}", "Body");
      expect(screen.getByTestId("email-preview-subject").textContent).toBe("Hi {{first_name}}");
      await waitFor(
        () => expect(screen.getByTestId("email-preview-subject").textContent).toBe("Hi Ada"),
        PREVIEW_WAIT,
      );
    });

    it("warns about unknown variables and disables both sends until the preview comes back clean", async () => {
      api.adminPreviewBroadcast.mockImplementation(async ({ subject, body }: { subject: string; body: string }) => ({
        subject, html: "<p>x</p>",
        unknown_variables: [subject, body].join(" ").includes("frist_name") ? ["frist_name"] : [],
      }));
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-audience-waitlist_all");
      fireEvent.click(screen.getByTestId("email-audience-waitlist_all"));
      fill("News", "Hi {{frist_name}},");

      const warning = await screen.findByTestId("email-unknown-variables", {}, PREVIEW_WAIT);
      expect(warning.textContent).toContain(
        "Unknown variable {{frist_name}}. Check the spelling, or pick one from Personalize.",
      );
      expect((screen.getByTestId("email-send") as HTMLButtonElement).disabled).toBe(true);
      expect((screen.getByTestId("email-send-test") as HTMLButtonElement).disabled).toBe(true);

      fill("News", "Hi {{first_name}},");
      await waitFor(() => expect(screen.queryByTestId("email-unknown-variables")).toBeNull(), PREVIEW_WAIT);
      expect((screen.getByTestId("email-send") as HTMLButtonElement).disabled).toBe(false);
      expect((screen.getByTestId("email-send-test") as HTMLButtonElement).disabled).toBe(false);
    });

    it("lists every unknown variable", async () => {
      api.adminPreviewBroadcast.mockResolvedValue({ subject: "s", html: "<p>x</p>", unknown_variables: ["frist_name", "nmae"] });
      render(<EmailBroadcastsTab />);
      const warning = await screen.findByTestId("email-unknown-variables", {}, PREVIEW_WAIT);
      expect(warning.textContent).toContain("Unknown variables {{frist_name}}, {{nmae}}.");
    });

    it("puts a send's 422 validation message in the toast, not the raw body", async () => {
      const msg = "Unknown variable {{frist_name}}. Use one of: {{first_name}}, {{name}}.";
      const body = { detail: [{ type: "value_error", loc: ["body", "body"], msg: `Value error, ${msg}` }] };
      api.adminSendTestBroadcast.mockRejectedValue(
        Object.assign(new Error(JSON.stringify(body)), { status: 422, body }),
      );
      render(<EmailBroadcastsTab />);
      await screen.findByTestId("email-send-test");
      fill("Subj", "Hi {{frist_name}}");
      fireEvent.click(screen.getByTestId("email-send-test"));
      await waitFor(() => expect(toastSpies.error).toHaveBeenCalledWith(`Test send failed: ${msg}`));
    });
  });
});
