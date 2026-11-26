import { describe, it, expect } from "vitest";
import {
  asBuildInteraction,
  decodeBuildAnswer,
  emptyBuildAssignment,
  encodeBuildAnswer,
  isBuildComplete,
  placeBuildItem,
} from "./buildInteraction";
import type { BuildInteraction } from "./types";

const NUCLEOTIDE: BuildInteraction = {
  kind: "build",
  slots: [
    { id: "head", label: "Head" },
    { id: "sugar", label: "Sugar" },
    { id: "base", label: "Base" },
  ],
  parts: [
    { id: "phosphate", label: "Phosphate" },
    { id: "deoxyribose", label: "Deoxyribose" },
    { id: "adenine", label: "Adenine" },
    { id: "amino", label: "Amino acid" },
  ],
};

describe("asBuildInteraction", () => {
  it("accepts equal counts or parts ≥ slots", () => {
    expect(asBuildInteraction(NUCLEOTIDE)).toEqual(NUCLEOTIDE);
    const equal: BuildInteraction = {
      kind: "build",
      slots: NUCLEOTIDE.slots,
      parts: NUCLEOTIDE.parts.slice(0, 3),
    };
    expect(asBuildInteraction(equal)).toEqual(equal);
  });

  it("rejects missing kind, empty sides, too few parts, and unsafe ids", () => {
    expect(asBuildInteraction(undefined)).toBeNull();
    expect(asBuildInteraction({ kind: "build", slots: [], parts: NUCLEOTIDE.parts })).toBeNull();
    expect(
      asBuildInteraction({
        kind: "build",
        slots: NUCLEOTIDE.slots,
        parts: NUCLEOTIDE.parts.slice(0, 2),
      }),
    ).toBeNull();
    expect(
      asBuildInteraction({
        kind: "build",
        slots: NUCLEOTIDE.slots,
        parts: [{ id: "bad=id", label: "Nope" }],
      }),
    ).toBeNull();
    expect(
      asBuildInteraction({
        kind: "build",
        slots: [{ id: "shared", label: "Head" }],
        parts: [{ id: "shared", label: "Phosphate" }],
      }),
    ).toBeNull();
  });
});

describe("encode / decode", () => {
  it("round-trips a complete assignment (extras stay in the tray)", () => {
    const assign = {
      phosphate: 0,
      deoxyribose: 1,
      adenine: 2,
      amino: null,
    };
    const encoded = encodeBuildAnswer(NUCLEOTIDE, assign);
    expect(encoded).toBe("head=phosphate;sugar=deoxyribose;base=adenine");
    expect(decodeBuildAnswer(NUCLEOTIDE, encoded)).toEqual(assign);
    expect(isBuildComplete(NUCLEOTIDE, assign)).toBe(true);
  });

  it("starts empty and is incomplete until every slot is filled", () => {
    const empty = emptyBuildAssignment(NUCLEOTIDE.parts);
    expect(isBuildComplete(NUCLEOTIDE, empty)).toBe(false);
    expect(encodeBuildAnswer(NUCLEOTIDE, empty)).toBe("head=;sugar=;base=");
    const partial = placeBuildItem(empty, "phosphate", 0);
    expect(isBuildComplete(NUCLEOTIDE, partial)).toBe(false);
    expect(decodeBuildAnswer(NUCLEOTIDE, "")).toEqual(empty);
  });

  it("moves a part between slots and back to the tray; displaces an occupant", () => {
    let assign = placeBuildItem(emptyBuildAssignment(NUCLEOTIDE.parts), "phosphate", 0);
    assign = placeBuildItem(assign, "deoxyribose", 0);
    expect(assign.phosphate).toBeNull();
    expect(assign.deoxyribose).toBe(0);
    assign = placeBuildItem(assign, "deoxyribose", 1);
    expect(assign.deoxyribose).toBe(1);
    assign = placeBuildItem(assign, "deoxyribose", null);
    expect(assign.deoxyribose).toBeNull();
  });
});
