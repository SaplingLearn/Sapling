// @vitest-environment jsdom
/**
 * crisisSupportOf / crisisSupportIn (docs/safety/crisis-support.md): the
 * client-side guard on the crisis card's payload. The fixture is the payload
 * the backend builds today (backend/tests/test_crisis_support_routes.py pins
 * its shape against services/crisis_support.client_payload).
 */
import { beforeEach, describe, expect, it } from "vitest";

import fixture from "@/test-utils/crisisSupport.json";
import {
  CARD_SHOWN_TTL_MS, crisisSupportIn, crisisSupportInError, crisisSupportOf, markNoteCardShown, takeNoteCardShown,
} from "./crisisSupport";
import { USER_SCOPED_SESSION_KEYS } from "./userScopedStorage";

describe("crisisSupportOf", () => {
  it("accepts the backend's payload unchanged", () => {
    expect(crisisSupportOf(fixture)).toEqual(fixture);
  });

  it("reads it off a whole response body", () => {
    expect(crisisSupportIn({ reply: "x", crisis_support: fixture })).toEqual(fixture);
    expect(crisisSupportIn({ reply: "an ordinary tutor reply" })).toBeNull();
    expect(crisisSupportIn({ crisis_support: null })).toBeNull();
    expect(crisisSupportIn(null)).toBeNull();
    expect(crisisSupportIn("text")).toBeNull();
  });

  it("reads it off an error answer's body (a note action refused with a 429)", () => {
    expect(crisisSupportInError({ status: 429, body: { detail: "Slow down.", crisis_support: fixture } })).toEqual(fixture);
    expect(crisisSupportInError({ status: 429, body: { detail: "Slow down." } })).toBeNull();
    expect(crisisSupportInError(new Error("network"))).toBeNull();
    expect(crisisSupportInError(undefined)).toBeNull();
    expect(crisisSupportInError(null)).toBeNull();
  });

  it("is null without a title or without any resource", () => {
    expect(crisisSupportOf({ ...fixture, title: undefined })).toBeNull();
    expect(crisisSupportOf({ ...fixture, resources: [] })).toBeNull();
    expect(crisisSupportOf({ ...fixture, resources: "988" })).toBeNull();
    expect(crisisSupportOf(undefined)).toBeNull();
  });

  it("drops any link that is not tel:, sms: or https:", () => {
    const hostile = {
      ...fixture,
      resources: [{
        id: "x", name: "X", detail: "d",
        actions: [
          { kind: "link", label: "js", href: "javascript:alert(1)" },
          { kind: "link", label: "plain http", href: "http://example.com" },
          { kind: "link", label: "data", href: "data:text/html,hi" },
          { kind: "call", label: "Call 988", href: "tel:988" },
          { kind: "link", label: "ok", href: "https://988lifeline.org" },
        ],
      }],
    };
    const out = crisisSupportOf(hostile)!;
    expect(out.resources[0].actions.map((a) => a.href)).toEqual(["tel:988", "https://988lifeline.org"]);
  });

  it("keeps a resource with no actions (the default campus entry has none)", () => {
    const campus = crisisSupportOf(fixture)!.resources.find((r) => r.id === "campus_counseling");
    expect(campus?.actions).toEqual([]);
  });
});

// Send to tutor showed the card beside its result; the /learn start it hands
// over carries the same card, which should not pop up a second time.
describe("markNoteCardShown / takeNoteCardShown", () => {
  beforeEach(() => sessionStorage.clear());

  it("is true once for the note whose card was just shown", () => {
    markNoteCardShown("n1", 1_000);
    expect(takeNoteCardShown("n1", 2_000)).toBe(true);
    expect(takeNoteCardShown("n1", 2_001)).toBe(false); // one-shot
  });

  it("is false for another note, and the mark is spent either way", () => {
    markNoteCardShown("n1", 1_000);
    expect(takeNoteCardShown("n2", 1_001)).toBe(false);
    expect(takeNoteCardShown("n1", 1_002)).toBe(false);
  });

  it("is false once the mark is stale, or dated in the future", () => {
    markNoteCardShown("n1", 1_000);
    expect(takeNoteCardShown("n1", 1_000 + CARD_SHOWN_TTL_MS + 1)).toBe(false);
    markNoteCardShown("n1", 5_000);
    expect(takeNoteCardShown("n1", 4_000)).toBe(false);
  });

  it("is false with no mark, or a mark that is not ours", () => {
    expect(takeNoteCardShown("n1")).toBe(false);
    sessionStorage.setItem(USER_SCOPED_SESSION_KEYS.find((k) => k.includes("crisis"))!, "{not json");
    expect(takeNoteCardShown("n1")).toBe(false);
  });

  it("is cleared with the rest of an account's session storage", () => {
    expect(USER_SCOPED_SESSION_KEYS.some((k) => k.includes("crisis_card_shown"))).toBe(true);
  });
});
