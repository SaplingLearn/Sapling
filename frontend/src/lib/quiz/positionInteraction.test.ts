import { describe, it, expect } from "vitest";
import {
  asPositionInteraction,
  decodePositionAnswer,
  encodePositionAnswer,
  isPositionComplete,
  placePositionMarker,
} from "./positionInteraction";
import type { PositionInteraction } from "./types";

const PH: PositionInteraction = {
  kind: "position",
  axisLabel: "pH scale",
  markers: [
    { id: "lemon", label: "Lemon juice" },
    { id: "water", label: "Pure water" },
    { id: "soda", label: "Baking soda" },
  ],
  stops: [
    { id: "2", label: "2" },
    { id: "7", label: "7" },
    { id: "9", label: "9" },
  ],
};

describe("asPositionInteraction", () => {
  it("accepts markers and stops", () => {
    expect(asPositionInteraction(PH)).toEqual(PH);
  });

  it("rejects collisions and short lists", () => {
    expect(asPositionInteraction(undefined)).toBeNull();
    expect(
      asPositionInteraction({
        kind: "position",
        markers: [{ id: "a", label: "A" }],
        stops: PH.stops,
      }),
    ).toBeNull();
  });
});

describe("encode / place", () => {
  it("round-trips placements", () => {
    let assign = placePositionMarker(
      { lemon: null, water: null, soda: null },
      "lemon",
      "2",
    );
    assign = placePositionMarker(assign, "water", "7");
    assign = placePositionMarker(assign, "soda", "9");
    const encoded = encodePositionAnswer(PH, assign);
    expect(encoded).toBe("lemon=2;water=7;soda=9");
    expect(isPositionComplete(PH, decodePositionAnswer(PH, encoded))).toBe(true);
  });
});
