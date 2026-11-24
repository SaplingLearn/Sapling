/**
 * W4 Stage 2: trust chrome copy stays honest (no "trust the AI") and stable
 * for CheckCard / ChatPanel title + aria-label wiring.
 */
import { describe, expect, it } from "vitest";

import {
  KEY_VERIFIED_HINT,
  KEY_VERIFIED_LABEL,
  MATERIALS_GROUNDED_HINT,
  MATERIALS_GROUNDED_LABEL,
} from "./loopTrustChrome";

describe("loopTrustChrome", () => {
  it("keeps short labels and honest tooltips (no trust-the-AI framing)", () => {
    expect(KEY_VERIFIED_LABEL).toBe("Key verified");
    expect(MATERIALS_GROUNDED_LABEL).toBe("Grounded in your materials");
    expect(KEY_VERIFIED_HINT.toLowerCase()).toContain("independent");
    expect(KEY_VERIFIED_HINT.toLowerCase()).toContain("answer key");
    expect(KEY_VERIFIED_HINT.toLowerCase()).not.toMatch(/trust the ai|trust us|ai verified/);
    expect(MATERIALS_GROUNDED_HINT.toLowerCase()).toContain("course materials");
    expect(MATERIALS_GROUNDED_HINT.toLowerCase()).not.toMatch(/trust the ai|cite list|chunk id/);
  });
});
