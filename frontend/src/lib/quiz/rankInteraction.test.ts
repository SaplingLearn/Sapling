import { describe, it, expect } from "vitest";
import {
  asRankInteraction,
  decodeRankAnswer,
  encodeRankAnswer,
  isRankComplete,
  placeRankItem,
} from "./rankInteraction";
import type { RankInteraction } from "./types";

const DX: RankInteraction = {
  kind: "rank",
  hint: "Most likely at the top.",
  whyPlaceholder: "Why is your top choice first?",
  items: [
    { id: "mi", label: "Myocardial infarction" },
    { id: "gerd", label: "GERD" },
    { id: "costo", label: "Costochondritis" },
  ],
};

describe("asRankInteraction", () => {
  it("accepts ≥2 items", () => {
    expect(asRankInteraction(DX)).toEqual(DX);
  });

  it("rejects short lists", () => {
    expect(asRankInteraction(undefined)).toBeNull();
  });
});

describe("encode / complete", () => {
  it("requires full order and a why", () => {
    let assign = placeRankItem({ mi: null, gerd: null, costo: null }, "mi", 0);
    assign = placeRankItem(assign, "gerd", 1);
    assign = placeRankItem(assign, "costo", 2);
    const encoded = encodeRankAnswer(DX, assign, "Radiating pain.");
    expect(encoded.startsWith("mi;gerd;costo")).toBe(true);
    expect(isRankComplete(DX, encoded)).toBe(true);
    expect(isRankComplete(DX, encodeRankAnswer(DX, assign, ""))).toBe(false);
    expect(decodeRankAnswer(DX, encoded).why).toBe("Radiating pain.");
  });
});
