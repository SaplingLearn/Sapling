import { describe, expect, it } from "vitest";
import type { GradescopeStatus } from "@/lib/api";
import {
  gradescopeConnectedVia,
  gradescopeModeLabel,
  gradescopeReauthMessage,
} from "./gradescopeState";

const status = (over: Partial<GradescopeStatus>): GradescopeStatus => ({
  has_credentials: true, auth_mode: "cookies", last_synced_at: null, ...over,
});

describe("how the Gradescope session was obtained", () => {
  it("prefers connected_via and derives it from auth_mode for an older backend", () => {
    expect(gradescopeConnectedVia(status({ connected_via: "bu_sso" }))).toBe("bu_sso");
    expect(gradescopeConnectedVia(status({ auth_mode: "password" }))).toBe("password");
    expect(gradescopeConnectedVia(status({ auth_mode: "cookies" }))).toBe("cookies");
    expect(gradescopeConnectedVia(status({ auth_mode: null, has_credentials: false }))).toBeNull();
  });

  it("labels each way of connecting", () => {
    expect(gradescopeModeLabel(status({ connected_via: "password" }))).toBe("password");
    expect(gradescopeModeLabel(status({ connected_via: "bu_sso" }))).toBe("BU SSO");
    expect(gradescopeModeLabel(status({ connected_via: "cookies" }))).toBe("session cookies (SSO)");
  });

  it("tells a password user to enter the password again, never that it was saved", () => {
    const msg = gradescopeReauthMessage(status({ connected_via: "password" }));
    expect(msg).toMatch(/Enter your Gradescope password again/);
    expect(msg).toMatch(/doesn't keep it/);
    expect(msg).not.toMatch(/saved/);
    expect(gradescopeReauthMessage(status({ connected_via: "bu_sso" }))).toMatch(/Sign in with BU again/);
  });
});
