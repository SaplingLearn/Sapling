import { describe, expect, it } from "vitest";
import { CLEANUP_WITHHELD_NOTICE, withheldNotice } from "./integrityNotice";

describe("withheldNotice (spec §13 A125)", () => {
  it("names one held-back item in the singular", () => {
    expect(withheldNotice(1, "card")).toBe(
      "1 card was held back because it would give away the answer to an open learning check. That check now counts as helped.",
    );
  });

  it("names several in the plural", () => {
    expect(withheldNotice(3, "concept")).toMatch(/^3 concepts were held back because they would give away/);
  });

  it("tells the student the cleanup left their cards unchanged", () => {
    expect(CLEANUP_WITHHELD_NOTICE).toContain("Your cards are unchanged");
  });
});
