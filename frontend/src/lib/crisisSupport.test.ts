/**
 * crisisSupportOf / crisisSupportIn (docs/safety/crisis-support.md): the
 * client-side guard on the crisis card's payload. The fixture is the payload
 * the backend builds today (backend/tests/test_crisis_support_routes.py pins
 * its shape against services/crisis_support.client_payload).
 */
import { describe, expect, it } from "vitest";

import fixture from "@/test-utils/crisisSupport.json";
import { crisisSupportIn, crisisSupportOf } from "./crisisSupport";

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
