import { describe, it, expect } from "vitest";
import {
  asSortInteraction,
  decodeSortAnswer,
  emptyAssignment,
  encodeSortAnswer,
  isSortComplete,
  placeSortItem,
} from "./sortInteraction";
import type { SortInteraction } from "./types";

const CELL: SortInteraction = {
  kind: "sort",
  buckets: ["Prokaryote", "Eukaryote"],
  items: [
    { id: "e-coli", label: "E. coli" },
    { id: "yeast", label: "Yeast" },
    { id: "amoeba", label: "Amoeba" },
    { id: "strep", label: "Streptococcus" },
  ],
};

describe("asSortInteraction", () => {
  it("accepts a well-formed Sort payload", () => {
    expect(asSortInteraction(CELL)).toEqual(CELL);
  });

  it("rejects missing kind, thin buckets, empty items, and unsafe ids", () => {
    expect(asSortInteraction(undefined)).toBeNull();
    expect(asSortInteraction({ kind: "sort", buckets: ["Only"], items: CELL.items })).toBeNull();
    expect(asSortInteraction({ kind: "sort", buckets: CELL.buckets, items: [] })).toBeNull();
    expect(
      asSortInteraction({
        kind: "sort",
        buckets: CELL.buckets,
        items: [{ id: "bad=id", label: "Nope" }],
      }),
    ).toBeNull();
  });
});

describe("encode / decode", () => {
  it("round-trips a complete assignment", () => {
    const assign = {
      "e-coli": 0,
      yeast: 1,
      amoeba: 1,
      strep: 0,
    };
    const encoded = encodeSortAnswer(CELL, assign);
    expect(encoded).toBe("Prokaryote=e-coli,strep;Eukaryote=yeast,amoeba");
    expect(decodeSortAnswer(CELL, encoded)).toEqual(assign);
    expect(isSortComplete(CELL, assign)).toBe(true);
  });

  it("starts empty and is incomplete until every item is placed", () => {
    const empty = emptyAssignment(CELL.items);
    expect(isSortComplete(CELL, empty)).toBe(false);
    expect(encodeSortAnswer(CELL, empty)).toBe("Prokaryote=;Eukaryote=");
    const partial = placeSortItem(empty, "e-coli", 0);
    expect(isSortComplete(CELL, partial)).toBe(false);
    expect(decodeSortAnswer(CELL, "")).toEqual(empty);
  });

  it("moves an item between buckets and back to the tray", () => {
    let assign = placeSortItem(emptyAssignment(CELL.items), "yeast", 0);
    assign = placeSortItem(assign, "yeast", 1);
    expect(assign.yeast).toBe(1);
    assign = placeSortItem(assign, "yeast", null);
    expect(assign.yeast).toBeNull();
  });
});
