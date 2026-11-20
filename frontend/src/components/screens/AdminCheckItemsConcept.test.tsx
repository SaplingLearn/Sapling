import { describe, expect, it } from "vitest";

import { conceptLabel } from "./AdminCheckItems";

describe("conceptLabel (spec §13 A141)", () => {
  it("names a concept's own item by its concept", () => {
    expect(conceptLabel("load factor")).toBe("load factor");
    expect(conceptLabel("load factor", [])).toBe("load factor");
  });

  it("names a multi-concept item by what it combines, apex first", () => {
    expect(conceptLabel("learning rate\u001fgradient descent", ["learning rate", "gradient descent"])).toBe(
      "Combines learning rate + gradient descent",
    );
    // a row that does not name its components (the key audit's) reads them off the key
    expect(conceptLabel("a\u001fb\u001fc")).toBe("Combines a + b + c");
  });
});
