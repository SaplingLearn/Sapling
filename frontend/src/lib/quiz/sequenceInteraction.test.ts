import { describe, it, expect } from "vitest";
import {
  asSequenceInteraction,
  decodeSequenceAnswer,
  emptySequenceAssignment,
  encodeSequenceAnswer,
  isSequenceComplete,
  placeSequenceItem,
} from "./sequenceInteraction";
import type { SequenceInteraction } from "./types";

const MITOSIS: SequenceInteraction = {
  kind: "sequence",
  steps: [
    { id: "prophase", label: "Prophase" },
    { id: "metaphase", label: "Metaphase" },
    { id: "anaphase", label: "Anaphase" },
    { id: "telophase", label: "Telophase" },
  ],
};

describe("asSequenceInteraction", () => {
  it("accepts a well-formed Sequence payload", () => {
    expect(asSequenceInteraction(MITOSIS)).toEqual(MITOSIS);
  });

  it("rejects missing kind, short lists, and unsafe ids", () => {
    expect(asSequenceInteraction(undefined)).toBeNull();
    expect(asSequenceInteraction({ kind: "sequence", steps: [] })).toBeNull();
    expect(
      asSequenceInteraction({
        kind: "sequence",
        steps: [{ id: "only", label: "One" }],
      }),
    ).toBeNull();
    expect(
      asSequenceInteraction({
        kind: "sequence",
        steps: [
          { id: "bad;id", label: "Nope" },
          { id: "ok", label: "Ok" },
        ],
      }),
    ).toBeNull();
  });
});

describe("encode / decode", () => {
  it("round-trips a complete assignment", () => {
    const assign = {
      prophase: 0,
      metaphase: 1,
      anaphase: 2,
      telophase: 3,
    };
    const encoded = encodeSequenceAnswer(MITOSIS, assign);
    expect(encoded).toBe("prophase;metaphase;anaphase;telophase");
    expect(decodeSequenceAnswer(MITOSIS, encoded)).toEqual(assign);
    expect(isSequenceComplete(MITOSIS, assign)).toBe(true);
  });

  it("starts empty and is incomplete until every slot is filled", () => {
    const empty = emptySequenceAssignment(MITOSIS.steps);
    expect(isSequenceComplete(MITOSIS, empty)).toBe(false);
    expect(encodeSequenceAnswer(MITOSIS, empty)).toBe(";;;");
    const partial = placeSequenceItem(empty, "prophase", 0);
    expect(isSequenceComplete(MITOSIS, partial)).toBe(false);
    expect(decodeSequenceAnswer(MITOSIS, "")).toEqual(empty);
  });

  it("displaces a previous step when placing into an occupied slot", () => {
    let assign = emptySequenceAssignment(MITOSIS.steps);
    assign = placeSequenceItem(assign, "prophase", 0);
    assign = placeSequenceItem(assign, "metaphase", 0);
    expect(assign.prophase).toBeNull();
    expect(assign.metaphase).toBe(0);
  });
});
