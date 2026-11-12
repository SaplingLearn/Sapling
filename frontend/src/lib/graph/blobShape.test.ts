import { describe, expect, it } from "vitest";
import {
  blobPath,
  blobProfile,
  nodeBlobPath,
  nodeBlobPathAt,
  rimFactor,
  rimRadius,
  wobbleFor,
} from "./blobShape";

/** Every number in a path, in order. */
const numbers = (d: string) => (d.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);

/** The anchor points of a path: the `M` point, then each curve's end point. */
function anchors(d: string): Array<[number, number]> {
  const n = numbers(d);
  const out: Array<[number, number]> = [[n[0], n[1]]];
  for (let i = 2; i < n.length; i += 6) out.push([n[i + 4], n[i + 5]]);
  return out;
}

const TURN = Math.PI * 2;
const IDS = ["a", "b", "n-rec", "n-trees", "concept-42", "root-c1", "", "Ünïcode", "x".repeat(200)];

describe("wobbleFor", () => {
  it("gives a small mark relatively more wobble than a large one", () => {
    expect(wobbleFor(8)).toBeCloseTo(0.13, 10);
    expect(wobbleFor(12)).toBeCloseTo(0.105, 10);
    expect(wobbleFor(22)).toBeCloseTo(0.055 + 0.6 / 22, 10);
    expect(wobbleFor(8)).toBeGreaterThan(wobbleFor(22));
  });

  it("stays between 7% and 13% of the radius", () => {
    expect(wobbleFor(1000)).toBe(0.07);
    expect(wobbleFor(40)).toBe(0.07);
    expect(wobbleFor(4)).toBe(0.13);
  });

  it("survives a zero, negative or missing radius", () => {
    expect(wobbleFor(0)).toBe(0.13);
    expect(wobbleFor(-5)).toBe(0.13);
    expect(wobbleFor(Number.NaN)).toBe(0.13);
  });
});

describe("blobProfile", () => {
  it("depends only on the node's id and the wobble", () => {
    for (const id of IDS) {
      expect(blobProfile(id, 0.1)).toEqual(blobProfile(id, 0.1));
    }
    // Returned from the cache: the very same object.
    expect(blobProfile("a", 0.1)).toBe(blobProfile("a", 0.1));
  });

  it("gives different nodes different shapes", () => {
    const seen = new Set(IDS.map((id) => JSON.stringify(blobProfile(id, 0.1))));
    expect(seen.size).toBe(IDS.length);
  });

  it("spends the whole wobble across the three harmonics, largest first", () => {
    for (const id of IDS) {
      for (const wobble of [0.07, 0.1, 0.13]) {
        const p = blobProfile(id, wobble);
        expect(p.a2 + p.a3 + p.a4).toBeCloseTo(wobble, 12);
        expect(p.a2).toBeGreaterThan(0);
        expect(p.a3).toBeGreaterThan(0);
        expect(p.a4).toBeGreaterThan(0);
        // The 2θ lean always outweighs the four-lobed ripple.
        expect(p.a2).toBeGreaterThan(p.a4);
        for (const phase of [p.p2, p.p3, p.p4]) {
          expect(phase).toBeGreaterThanOrEqual(0);
          expect(phase).toBeLessThan(TURN);
        }
      }
    }
  });

  it("scales with the wobble: the same shape, more or less pronounced", () => {
    const small = blobProfile("n-rec", 0.07);
    const large = blobProfile("n-rec", 0.13);
    expect(large.p2).toBe(small.p2);
    expect(large.p3).toBe(small.p3);
    expect(large.p4).toBe(small.p4);
    expect(large.a2 / small.a2).toBeCloseTo(0.13 / 0.07, 10);
    expect(large.a3 / small.a3).toBeCloseTo(0.13 / 0.07, 10);
  });

  it("answers the same after its cache fills and is emptied", () => {
    const before = { ...blobProfile("cache-probe", 0.1) };
    for (let i = 0; i < 4100; i++) blobProfile(`cache-filler-${i}`, 0.1);
    expect(blobProfile("cache-probe", 0.1)).toEqual(before);
  });
});

describe("rimFactor / rimRadius", () => {
  it("never leaves the circle by more than the wobble", () => {
    for (const id of IDS) {
      const wobble = 0.13;
      const p = blobProfile(id, wobble);
      for (let i = 0; i < 360; i++) {
        const f = rimFactor(p, (i / 360) * TURN);
        expect(f).toBeGreaterThanOrEqual(1 - wobble - 1e-12);
        expect(f).toBeLessThanOrEqual(1 + wobble + 1e-12);
      }
    }
  });

  it("is not a circle", () => {
    for (const id of IDS) {
      const p = blobProfile(id, 0.1);
      const fs = Array.from({ length: 360 }, (_, i) => rimFactor(p, (i / 360) * TURN));
      expect(Math.max(...fs) - Math.min(...fs)).toBeGreaterThan(0.02);
    }
  });

  it("averages to the nominal radius, so a blob is as big as the circle it replaces", () => {
    for (const id of IDS) {
      const p = blobProfile(id, 0.13);
      let sum = 0;
      for (let i = 0; i < 720; i++) sum += rimFactor(p, (i / 720) * TURN);
      expect(sum / 720).toBeCloseTo(1, 10);
    }
  });

  it("stays centred: no first harmonic pulls the shape off its centre", () => {
    for (const id of IDS) {
      const p = blobProfile(id, 0.13);
      let x = 0;
      let y = 0;
      for (let i = 0; i < 720; i++) {
        const theta = (i / 720) * TURN;
        x += rimFactor(p, theta) * Math.cos(theta);
        y += rimFactor(p, theta) * Math.sin(theta);
      }
      expect(x / 720).toBeCloseTo(0, 10);
      expect(y / 720).toBeCloseTo(0, 10);
    }
  });

  it("is periodic over a full turn", () => {
    const p = blobProfile("n-rec", 0.1);
    for (const theta of [0, 0.4, 1.7, 3.1, 5.9]) {
      expect(rimFactor(p, theta + TURN)).toBeCloseTo(rimFactor(p, theta), 12);
      expect(rimFactor(p, theta - TURN)).toBeCloseTo(rimFactor(p, theta), 12);
    }
  });

  it("rimRadius is the factor times the radius", () => {
    const p = blobProfile("n-rec", 0.1);
    expect(rimRadius(p, 14, 1.2)).toBe(14 * rimFactor(p, 1.2));
    expect(rimRadius(p, 0, 1.2)).toBe(0);
  });
});

describe("blobPath", () => {
  it("is one closed curve of sixteen cubic segments", () => {
    for (const id of IDS) {
      const d = blobPath(blobProfile(id, 0.1), 12);
      expect(d).toMatch(/^M-?[\d.]+ -?[\d.]+(C(-?[\d.]+ ){5}-?[\d.]+){16}Z$/);
      const pts = anchors(d);
      expect(pts).toHaveLength(17);
      // Closed on itself: the last curve ends where the path began.
      expect(pts[16]).toEqual(pts[0]);
    }
  });

  it("passes through the outline at each sample direction", () => {
    const p = blobProfile("n-trees", 0.1);
    const r = 15;
    const pts = anchors(blobPath(p, r));
    for (let i = 0; i < 16; i++) {
      const theta = (i / 16) * TURN;
      const rr = rimRadius(p, r, theta);
      // Written to two decimals.
      expect(pts[i][0]).toBeCloseTo(rr * Math.cos(theta), 2);
      expect(pts[i][1]).toBeCloseTo(rr * Math.sin(theta), 2);
    }
  });

  it("stays inside the ring the wobble allows, control points included", () => {
    for (const id of IDS) {
      const wobble = 0.13;
      const r = 20;
      const n = numbers(blobPath(blobProfile(id, wobble), r));
      for (let i = 0; i < n.length; i += 2) {
        const dist = Math.hypot(n[i], n[i + 1]);
        expect(dist).toBeGreaterThan(r * (1 - wobble) - 0.5);
        // A control point sits outside the curve it bends, by a little.
        expect(dist).toBeLessThan(r * (1 + wobble) * 1.06);
      }
    }
  });

  it("writes plain numbers: finite, at most two decimals, no trailing zeros, no negative zero", () => {
    for (const id of IDS) {
      const d = blobPath(blobProfile(id, 0.13), 9.37);
      expect(d).not.toMatch(/NaN|Infinity|undefined|e[+-]?\d/);
      for (const token of d.match(/-?\d+(?:\.\d+)?/g) ?? []) {
        expect(token).toMatch(/^-?\d+(\.\d{1,2})?$/);
        expect(token).not.toMatch(/\.\d*0$/);
        expect(token).not.toBe("-0");
      }
    }
  });

  it("scales with the radius without changing shape", () => {
    const p = blobProfile("n-rec", 0.1);
    const small = numbers(blobPath(p, 10));
    const large = numbers(blobPath(p, 30));
    expect(large).toHaveLength(small.length);
    // Each coordinate is rounded to two decimals before and after scaling.
    for (let i = 0; i < small.length; i++) expect(large[i]).toBeCloseTo(small[i] * 3, 1);
  });

  it("moves with its centre", () => {
    const p = blobProfile("n-rec", 0.1);
    const origin = numbers(blobPath(p, 12));
    const moved = numbers(blobPath(p, 12, 140, -60));
    expect(moved).toHaveLength(origin.length);
    for (let i = 0; i < origin.length; i += 2) {
      expect(moved[i]).toBeCloseTo(origin[i] + 140, 1);
      expect(moved[i + 1]).toBeCloseTo(origin[i + 1] - 60, 1);
    }
  });

  it("collapses to a point at radius zero rather than failing", () => {
    const d = blobPath(blobProfile("n-rec", 0.1), 0);
    expect(new Set(numbers(d))).toEqual(new Set([0]));
  });
});

describe("nodeBlobPath / nodeBlobPathAt", () => {
  it("is the node's own outline about the origin", () => {
    for (const id of IDS) {
      expect(nodeBlobPath(id, 12, 0.1)).toBe(blobPath(blobProfile(id, 0.1), 12));
    }
  });

  it("is stable across calls, and distinct per node, radius and wobble", () => {
    const d = nodeBlobPath("n-rec", 12, 0.1);
    expect(nodeBlobPath("n-rec", 12, 0.1)).toBe(d);
    expect(nodeBlobPath("n-trees", 12, 0.1)).not.toBe(d);
    expect(nodeBlobPath("n-rec", 13, 0.1)).not.toBe(d);
    expect(nodeBlobPath("n-rec", 12, 0.12)).not.toBe(d);
  });

  it("answers the same after its cache fills and is emptied", () => {
    const before = nodeBlobPath("path-cache-probe", 12, 0.1);
    for (let i = 0; i < 6100; i++) nodeBlobPath("path-cache-probe", 12 + i * 0.01 + 1, 0.1);
    expect(nodeBlobPath("path-cache-probe", 12, 0.1)).toBe(before);
  });

  it("nodeBlobPathAt bakes the centre into the same outline", () => {
    expect(nodeBlobPathAt("n-rec", 12, 0.1, 0, 0)).toBe(nodeBlobPath("n-rec", 12, 0.1));
    expect(nodeBlobPathAt("n-rec", 12, 0.1, 140, 90)).toBe(blobPath(blobProfile("n-rec", 0.1), 12, 140, 90));
    expect(anchors(nodeBlobPathAt("n-rec", 12, 0.1, 140, 90))[0][0]).toBeGreaterThan(140);
  });
});
