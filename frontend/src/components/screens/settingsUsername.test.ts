import { describe, it, expect } from "vitest";
import {
  usernameBorderColor,
  usernameMessageColor,
  usernameMessageText,
  type UsernameState,
} from "./settingsUsername";

const STATUSES: UsernameState["status"][] = ["idle", "checking", "available", "taken", "invalid"];

describe("usernameBorderColor", () => {
  it.each([
    ["idle", "var(--border)"],
    ["checking", "var(--border)"],
    ["available", "var(--border)"],
    ["taken", "var(--err)"],
    ["invalid", "var(--err)"],
  ] as const)("%s → %s", (status, color) => {
    expect(usernameBorderColor(status)).toBe(color);
  });
});

describe("usernameMessageColor", () => {
  it.each([
    ["idle", "var(--err)"],
    ["checking", "var(--text-muted)"],
    ["available", "var(--accent)"],
    ["taken", "var(--err)"],
    ["invalid", "var(--err)"],
  ] as const)("%s → %s", (status, color) => {
    expect(usernameMessageColor(status)).toBe(color);
  });
});

describe("usernameMessageText", () => {
  it("says Checking… while checking, whatever the message", () => {
    expect(usernameMessageText({ status: "checking", message: "Available" })).toBe("Checking…");
    expect(usernameMessageText({ status: "checking" })).toBe("Checking…");
  });

  it("otherwise shows the verdict's own message (or nothing)", () => {
    for (const status of STATUSES.filter(s => s !== "checking")) {
      expect(usernameMessageText({ status, message: "m" })).toBe("m");
      expect(usernameMessageText({ status })).toBeUndefined();
    }
  });
});
