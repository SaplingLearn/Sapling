import { describe, it, expect } from "vitest";
import {
  asConnectInteraction,
  decodeConnectAnswer,
  encodeConnectAnswer,
  isConnectComplete,
  pairConnect,
} from "./connectInteraction";
import type { ConnectInteraction } from "./types";

const DRUGS: ConnectInteraction = {
  kind: "connect",
  note: "Match each drug to its mechanism.",
  left: [
    { id: "aspirin", label: "Aspirin" },
    { id: "penicillin", label: "Penicillin" },
  ],
  right: [
    { id: "cox", label: "Inhibits COX enzymes" },
    { id: "wall", label: "Inhibits bacterial cell wall synthesis" },
  ],
};

describe("asConnectInteraction", () => {
  it("accepts equal left/right lists", () => {
    expect(asConnectInteraction(DRUGS)).toEqual(DRUGS);
  });

  it("rejects unequal or overlapping ids", () => {
    expect(asConnectInteraction(undefined)).toBeNull();
    expect(
      asConnectInteraction({
        kind: "connect",
        left: DRUGS.left,
        right: [DRUGS.right[0]],
      }),
    ).toBeNull();
  });
});

describe("encode / pair", () => {
  it("round-trips a full matching", () => {
    let assign = pairConnect({ aspirin: null, penicillin: null }, "aspirin", "cox");
    assign = pairConnect(assign, "penicillin", "wall");
    const encoded = encodeConnectAnswer(DRUGS, assign);
    expect(encoded).toBe("aspirin=cox;penicillin=wall");
    expect(isConnectComplete(DRUGS, decodeConnectAnswer(DRUGS, encoded))).toBe(true);
  });
});
