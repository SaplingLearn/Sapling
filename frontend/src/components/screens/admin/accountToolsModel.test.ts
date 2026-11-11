import { describe, expect, it } from "vitest";
import type { AdminAccountSummary, AdminAccountsMeta, AdminUserListItem } from "@/lib/types";
import {
  accountHandles, canConfirmReview, isCopyBlocked, metaView, type ReviewData, type ReviewState,
} from "./accountToolsModel";

const USER: AdminUserListItem = {
  id: "u-ada", name: "Ada Lovelace", email: "Ada@bu.edu", is_approved: true,
  last_sign_in_at: null, created_at: "2026-10-01T00:00:00Z", roles: [],
};

const summary = (exists: boolean): AdminAccountSummary => ({
  exists, courses: [], counts: {}, total_xp: 0, empty: true,
});

const copyReview = (source: boolean, destination: boolean): ReviewState => ({
  status: "ready",
  data: {
    kind: "copy",
    preview: {
      direction: "push",
      source: { env: "staging", summary: summary(source) },
      destination: { env: "production", summary: summary(destination) },
    },
  },
});

const META: AdminAccountsMeta = {
  env: "staging",
  majors: [
    { key: "cs", label: "Computer Science", courses: [] },
    { key: "biology", label: "Biology", courses: [] },
  ],
  sync: { configured: true, peer_env: "production" },
} as AdminAccountsMeta;

describe("accountHandles", () => {
  it("confirms by the trimmed email and names by name", () => {
    expect(accountHandles({ ...USER, email: "  Ada@bu.edu " })).toEqual({
      target: "Ada@bu.edu", targetIsEmail: true, who: "Ada Lovelace",
    });
  });

  it("falls back to the user id for a null or blank email", () => {
    expect(accountHandles({ ...USER, email: null })).toEqual({
      target: "u-ada", targetIsEmail: false, who: "Ada Lovelace",
    });
    expect(accountHandles({ ...USER, email: "   " })).toEqual({
      target: "u-ada", targetIsEmail: false, who: "Ada Lovelace",
    });
  });

  it("names by email, then id, when the name is empty", () => {
    expect(accountHandles({ ...USER, name: "" }).who).toBe("Ada@bu.edu");
    expect(accountHandles({ ...USER, name: "", email: null }).who).toBe("u-ada");
    // A blank (but non-empty) email still names the account, untrimmed.
    expect(accountHandles({ ...USER, name: "", email: "  " }).who).toBe("  ");
  });
});

describe("isCopyBlocked", () => {
  it("is false without a loaded review", () => {
    expect(isCopyBlocked(null)).toBe(false);
    expect(isCopyBlocked({ status: "loading" })).toBe(false);
    expect(isCopyBlocked({ status: "error", message: "x" })).toBe(false);
  });

  it("is false for a local review, even of a missing account", () => {
    expect(isCopyBlocked({ status: "ready", data: { kind: "local", summary: summary(false) } })).toBe(false);
  });

  it("blocks a copy when either side's account is missing", () => {
    expect(isCopyBlocked(copyReview(true, true))).toBe(false);
    expect(isCopyBlocked(copyReview(false, true))).toBe(true);
    expect(isCopyBlocked(copyReview(true, false))).toBe(true);
    expect(isCopyBlocked(copyReview(false, false))).toBe(true);
  });
});

describe("metaView", () => {
  it("is empty before meta loads", () => {
    expect(metaView(null, "cs")).toEqual({ selectedMajor: null, peer: null, env: "" });
  });

  it("selects the major by key, with the peer and env", () => {
    expect(metaView(META, "biology")).toEqual({ selectedMajor: META.majors[1], peer: "production", env: "staging" });
  });

  it("has no selected major for an unknown key, and a null peer when unreachable", () => {
    const unreachable = { ...META, sync: { configured: true, peer_env: null } };
    expect(metaView(unreachable, "")).toEqual({ selectedMajor: null, peer: null, env: "staging" });
  });
});

describe("canConfirmReview", () => {
  const ready: ReviewData = { kind: "local", summary: summary(true) };
  const ok = { ready, armed: true, busy: false, blocked: false, meta: META };

  it("allows a loaded, armed, unblocked review with nothing running", () => {
    expect(canConfirmReview(ok)).toBe(true);
  });

  it.each([
    ["no loaded review", { ready: null }],
    ["handle not typed", { armed: false }],
    ["an action running", { busy: true }],
    ["a blocked copy", { blocked: true }],
    ["no meta", { meta: null }],
  ])("refuses with %s", (_why, override) => {
    expect(canConfirmReview({ ...ok, ...override })).toBe(false);
  });
});
