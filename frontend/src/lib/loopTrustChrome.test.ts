/**
 * W4 Stage 2: trust chrome copy stays honest (no "trust the AI") and stable
 * for the ChatPanel title + aria-label wiring. (The check card's "Key
 * verified" line was removed in the Tutor redesign's subtract pass.)
 */
import { describe, expect, it } from "vitest";

import {
  MATERIALS_GROUNDED_HINT,
  MATERIALS_GROUNDED_LABEL,
} from "./loopTrustChrome";

describe("loopTrustChrome", () => {
  it("keeps a short label and an honest tooltip (no trust-the-AI framing)", () => {
    expect(MATERIALS_GROUNDED_LABEL).toBe("Grounded in your materials");
    expect(MATERIALS_GROUNDED_HINT.toLowerCase()).toContain("course materials");
    expect(MATERIALS_GROUNDED_HINT.toLowerCase()).not.toMatch(/trust the ai|cite list|chunk id/);
  });
});
