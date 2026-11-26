import { describe, it, expect } from "vitest";
import {
  asConnectInteraction,
  decodeConnectAnswer,
  decodeConnectMapAnswer,
  encodeConnectAnswer,
  encodeConnectMapAnswer,
  isConnectComplete,
  isConnectMapComplete,
  pairConnect,
  toggleConnectMapEdge,
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

const MAP: ConnectInteraction = {
  kind: "connect",
  mode: "map",
  note: "Link related ideas.",
  left: [],
  right: [],
  nodes: [
    { id: "deriv", label: "Derivative" },
    { id: "limit", label: "Limit" },
    { id: "slope", label: "Slope" },
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

  it("accepts concept-map mode with ≥3 nodes", () => {
    expect(asConnectInteraction(MAP)).toEqual(MAP);
    expect(
      asConnectInteraction({
        kind: "connect",
        mode: "map",
        left: [],
        right: [],
        nodes: MAP.nodes!.slice(0, 2),
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

describe("concept-map edges", () => {
  it("round-trips undirected edges and completeness", () => {
    let edges = toggleConnectMapEdge([], "deriv", "limit");
    edges = toggleConnectMapEdge(edges, "limit", "slope");
    const encoded = encodeConnectMapAnswer(edges);
    expect(encoded).toBe("deriv=limit;limit=slope");
    const decoded = decodeConnectMapAnswer(MAP, encoded);
    expect(isConnectMapComplete(MAP, decoded)).toBe(true);
  });

  it("toggles an edge off", () => {
    const once = toggleConnectMapEdge([], "a", "b");
    expect(encodeConnectMapAnswer(once)).toBe("a=b");
    expect(encodeConnectMapAnswer(toggleConnectMapEdge(once, "b", "a"))).toBe("");
  });
});
