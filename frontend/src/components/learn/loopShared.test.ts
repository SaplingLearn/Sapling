import { describe, expect, it } from "vitest";

import { hintDenial } from "./loopShared";

describe("hintDenial (#866 K32)", () => {
  it("a written attempt time alone held back is too_soon, whatever the wait", () => {
    expect(hintDenial("no_genuine_attempt", undefined, 12.5)).toBe("too_soon");
    // a server wait of 0 is still a wait: never "write what you think"
    expect(hintDenial("no_genuine_attempt", undefined, 0)).toBe("too_soon");
  });

  it("no wait from /step/attempt keeps the server's reason", () => {
    expect(hintDenial("no_genuine_attempt", undefined, undefined)).toBe("no_genuine_attempt");
    expect(hintDenial("dwell", undefined, 3)).toBe("dwell");
  });

  it("an H6 gate another try lifts is h6_attempt; any other stays h6_gate", () => {
    expect(hintDenial("h6_gate", "attempt", undefined)).toBe("h6_attempt");
    expect(hintDenial("h6_gate", undefined, undefined)).toBe("h6_gate");
  });
});
