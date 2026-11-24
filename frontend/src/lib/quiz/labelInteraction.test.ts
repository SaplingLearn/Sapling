import { describe, it, expect } from "vitest";
import {
  asLabelInteraction,
  decodeLabelAnswer,
  emptyLabelAssignment,
  encodeLabelAnswer,
  isLabelComplete,
  placeLabelItem,
} from "./labelInteraction";
import type { LabelInteraction } from "./types";

const HEART: LabelInteraction = {
  kind: "label",
  spots: [
    { id: "1", label: "1" },
    { id: "2", label: "2" },
    { id: "3", label: "3" },
    { id: "4", label: "4" },
  ],
  labels: [
    { id: "aorta", label: "Aorta" },
    { id: "pa", label: "Pulmonary artery" },
    { id: "ra", label: "Right atrium" },
    { id: "lv", label: "Left ventricle" },
  ],
};

describe("asLabelInteraction", () => {
  it("accepts a well-formed Label payload", () => {
    expect(asLabelInteraction(HEART)).toEqual(HEART);
  });

  it("rejects missing kind, empty sides, unequal counts, and unsafe ids", () => {
    expect(asLabelInteraction(undefined)).toBeNull();
    expect(asLabelInteraction({ kind: "label", spots: [], labels: HEART.labels })).toBeNull();
    expect(
      asLabelInteraction({
        kind: "label",
        spots: HEART.spots.slice(0, 2),
        labels: HEART.labels,
      }),
    ).toBeNull();
    expect(
      asLabelInteraction({
        kind: "label",
        spots: HEART.spots,
        labels: [{ id: "bad=id", label: "Nope" }],
      }),
    ).toBeNull();
    expect(
      asLabelInteraction({
        kind: "label",
        spots: [{ id: "shared", label: "1" }],
        labels: [{ id: "shared", label: "Aorta" }],
      }),
    ).toBeNull();
  });
});

describe("encode / decode", () => {
  it("round-trips a complete assignment", () => {
    const assign = {
      aorta: 0,
      pa: 1,
      ra: 2,
      lv: 3,
    };
    const encoded = encodeLabelAnswer(HEART, assign);
    expect(encoded).toBe("1=aorta;2=pa;3=ra;4=lv");
    expect(decodeLabelAnswer(HEART, encoded)).toEqual(assign);
    expect(isLabelComplete(HEART, assign)).toBe(true);
  });

  it("starts empty and is incomplete until every label is placed", () => {
    const empty = emptyLabelAssignment(HEART.labels);
    expect(isLabelComplete(HEART, empty)).toBe(false);
    expect(encodeLabelAnswer(HEART, empty)).toBe("1=;2=;3=;4=");
    const partial = placeLabelItem(empty, "aorta", 0);
    expect(isLabelComplete(HEART, partial)).toBe(false);
    expect(decodeLabelAnswer(HEART, "")).toEqual(empty);
  });

  it("moves a label between spots and back to the tray; displaces an occupant", () => {
    let assign = placeLabelItem(emptyLabelAssignment(HEART.labels), "aorta", 0);
    assign = placeLabelItem(assign, "pa", 0);
    expect(assign.aorta).toBeNull();
    expect(assign.pa).toBe(0);
    assign = placeLabelItem(assign, "pa", 1);
    expect(assign.pa).toBe(1);
    assign = placeLabelItem(assign, "pa", null);
    expect(assign.pa).toBeNull();
  });
});
