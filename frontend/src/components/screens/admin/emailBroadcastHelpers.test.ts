import { describe, expect, it } from "vitest";

import type { EmailBroadcast, EmailBroadcastPreview } from "@/lib/types";

import {
  audienceLabel, broadcastChipClass, broadcastDate, broadcastStatusLabel, confirmMatches, deriveSendGate,
  isAnySending, people, spliceAtSelection, token, variableTitle, type SendGateInput,
} from "./emailBroadcastHelpers";

const AUDIENCES = [
  { key: "waitlist_all" as const, label: "Everyone", count: 12 },
  { key: "waitlist_pending" as const, label: "Pending", count: 0 },
];

const row = (over: Partial<EmailBroadcast> = {}): EmailBroadcast => ({
  id: "b", subject: "s", audience: "users_all", status: "sent", recipient_count: 1, sent_count: 1,
  skipped_count: 0, failed_count: 0, created_at: "2026-10-20T10:00:00Z", sent_at: null, created_by: null,
  ...over,
});

describe("people / token", () => {
  it("pluralizes", () => {
    expect(people(0)).toBe("0 people");
    expect(people(1)).toBe("1 person");
    expect(people(2)).toBe("2 people");
  });
  it("wraps a key in braces", () => {
    expect(token("first_name")).toBe("{{first_name}}");
  });
});

describe("broadcastChipClass", () => {
  it("maps each status, and an unknown one to the plain chip", () => {
    expect(broadcastChipClass("sending")).toBe("chip chip--info");
    expect(broadcastChipClass("sent")).toBe("chip chip--accent");
    expect(broadcastChipClass("partial")).toBe("chip chip--warn");
    expect(broadcastChipClass("failed")).toBe("chip chip--warn");
    expect(broadcastChipClass("skipped")).toBe("chip");
    expect(broadcastChipClass("bogus" as EmailBroadcast["status"])).toBe("chip");
  });
});

describe("broadcastStatusLabel", () => {
  it("says stalled for a stale run, else the status", () => {
    expect(broadcastStatusLabel({ status: "sending", stale: true })).toBe("stalled");
    expect(broadcastStatusLabel({ status: "sending", stale: false })).toBe("sending");
    expect(broadcastStatusLabel({ status: "failed" })).toBe("failed");
  });
});

describe("broadcastDate", () => {
  it("prefers sent_at, falling back to created_at", () => {
    expect(broadcastDate({ sent_at: "2026-10-21T00:00:00Z", created_at: "2026-10-20T00:00:00Z" }))
      .toBe(new Date("2026-10-21T00:00:00Z").toLocaleString());
    expect(broadcastDate({ sent_at: null, created_at: "2026-10-20T00:00:00Z" }))
      .toBe(new Date("2026-10-20T00:00:00Z").toLocaleString());
  });
});

describe("audienceLabel", () => {
  it("returns the label, or the raw key when unknown", () => {
    expect(audienceLabel(AUDIENCES, "waitlist_all")).toBe("Everyone");
    expect(audienceLabel(AUDIENCES, "mystery")).toBe("mystery");
    expect(audienceLabel([], "x")).toBe("x");
  });
});

describe("isAnySending", () => {
  it("is true only for a live (non-stale) sending row", () => {
    expect(isAnySending([])).toBe(false);
    expect(isAnySending([row({ status: "sent" })])).toBe(false);
    expect(isAnySending([row({ status: "sending", stale: true })])).toBe(false);
    expect(isAnySending([row({ status: "sent" }), row({ status: "sending" })])).toBe(true);
  });
});

describe("variableTitle", () => {
  it("describes a button variable, a fallback, or just the token", () => {
    expect(variableTitle({ key: "signin_link", label: "", fallback: "x", example: "", button: "Sign in" }))
      .toBe("{{signin_link}}\nOn its own line it's a \"Sign in\" button. {{signin_link|Your label}} changes the label.");
    expect(variableTitle({ key: "first_name", label: "", fallback: "there", example: "" }))
      .toBe("{{first_name}}\nIf unknown: there");
    expect(variableTitle({ key: "email", label: "", fallback: "", example: "" })).toBe("{{email}}");
    expect(variableTitle({ key: "email", label: "", fallback: "", example: "", button: "" })).toBe("{{email}}");
  });
});

describe("confirmMatches", () => {
  it("accepts the count or SEND, trimmed, and nothing else", () => {
    expect(confirmMatches("12", 12)).toBe(true);
    expect(confirmMatches(" 12 ", 12)).toBe(true);
    expect(confirmMatches("SEND", 12)).toBe(true);
    expect(confirmMatches(" SEND ", 0)).toBe(true);
    expect(confirmMatches("send", 12)).toBe(false);
    expect(confirmMatches("11", 12)).toBe(false);
    expect(confirmMatches("", 0)).toBe(false);
    expect(confirmMatches("0", 0)).toBe(true);
  });
});

describe("spliceAtSelection", () => {
  it("replaces the selection and reports where the insert starts", () => {
    expect(spliceAtSelection("Hi XX!", { selectionStart: 3, selectionEnd: 5 }, "{{a}}"))
      .toEqual({ start: 3, next: "Hi {{a}}!" });
  });
  it("appends when there's no element or no selection", () => {
    expect(spliceAtSelection("abc", null, "T")).toEqual({ start: 3, next: "abcT" });
    expect(spliceAtSelection("abc", { selectionStart: null, selectionEnd: null }, "T")).toEqual({ start: 3, next: "abcT" });
  });
  it("clamps a selection past the end and an inverted one", () => {
    expect(spliceAtSelection("abc", { selectionStart: 9, selectionEnd: 12 }, "T")).toEqual({ start: 3, next: "abcT" });
    expect(spliceAtSelection("abcd", { selectionStart: 2, selectionEnd: 1 }, "T")).toEqual({ start: 2, next: "abTcd" });
    expect(spliceAtSelection("abcd", { selectionStart: 1, selectionEnd: null }, "T")).toEqual({ start: 1, next: "aTbcd" });
  });
});

describe("deriveSendGate", () => {
  const preview = (over: Partial<EmailBroadcastPreview> = {}): EmailBroadcastPreview => ({ subject: "S", html: "", ...over });
  const ready: SendGateInput = {
    audiences: AUDIENCES, audience: "waitlist_all", subject: " S ", body: "B ",
    preview: preview(), previewFor: { subject: "S", body: "B" },
    status: { configured: true, from_address: "" }, sending: false, confirmText: "",
  };

  it("allows a send when everything lines up", () => {
    const g = deriveSendGate(ready);
    expect(g).toMatchObject({
      n: 12, hasDraft: true, previewCurrent: true, unknownVars: [], hasUnknown: false,
      canSend: true, notConfigured: false, confirmOk: false,
    });
    expect(g.selectedAudience).toBe(AUDIENCES[0]);
    expect(deriveSendGate({ ...ready, confirmText: "12" }).confirmOk).toBe(true);
  });

  it("blocks on each missing piece", () => {
    expect(deriveSendGate({ ...ready, subject: "  " }).canSend).toBe(false);
    expect(deriveSendGate({ ...ready, body: "" }).hasDraft).toBe(false);
    expect(deriveSendGate({ ...ready, audience: null })).toMatchObject({ canSend: false, n: 0, selectedAudience: null });
    expect(deriveSendGate({ ...ready, audience: "waitlist_pending" })).toMatchObject({ canSend: false, n: 0 });
    expect(deriveSendGate({ ...ready, sending: true }).canSend).toBe(false);
    expect(deriveSendGate({ ...ready, preview: null })).toMatchObject({ previewCurrent: false, canSend: false });
    expect(deriveSendGate({ ...ready, previewFor: null }).previewCurrent).toBe(false);
    expect(deriveSendGate({ ...ready, previewFor: { subject: "S", body: "old" } }).previewCurrent).toBe(false);
  });

  it("blocks on unknown variables", () => {
    const g = deriveSendGate({ ...ready, preview: preview({ unknown_variables: ["x"] }) });
    expect(g).toMatchObject({ unknownVars: ["x"], hasUnknown: true, canSend: false, previewCurrent: true });
  });

  it("flags a not-configured status, but not a missing one", () => {
    expect(deriveSendGate({ ...ready, status: { configured: false, from_address: "" } }).notConfigured).toBe(true);
    expect(deriveSendGate({ ...ready, status: null }).notConfigured).toBe(false);
  });

  it("compares the trimmed draft against the previewed one", () => {
    // ["a","b c"] vs ["a b","c"] must not collide.
    const g = deriveSendGate({ ...ready, subject: "a", body: "b c", previewFor: { subject: "a b", body: "c" } });
    expect(g.previewCurrent).toBe(false);
  });
});
