import { describe, expect, it } from "vitest";
import { blobProfile, rimRadius, wobbleFor } from "@/lib/graph/blobShape";
import { NODE_STROKE_OPACITY, TIER_OPACITY, edgeWidthFor } from "@/lib/graph/nodeStyle";
import {
  ANCHOR_WIDTH,
  ARROW_REF_X,
  ARROW_SIZE,
  ARROW_ZOOM,
  conceptLabelOpacity,
  conceptLabelSize,
  conceptLabelWeight,
  hoverFocusId,
  hoverMastery,
  inCourseFocus,
  isDragPinned,
  legibleLinkOpacity,
  legibleNodeOpacity,
  linkArrow,
  linkEnd,
  linkIncident,
  linkMarker,
  linkStroke,
  nodeOpacity,
  nodeStrokeOpacity,
  organicLinkSegment,
  plainLinkOpacity,
  relatedDash,
} from "./knowledgeGraph2DPaint";

const c1 = { course_id: "c1" };
const c2 = { course_id: "c2" };

describe("linkEnd", () => {
  const a = { id: "a" };
  const byId = new Map([["a", a]]);
  it("returns a node end as is", () => expect(linkEnd(a, new Map())).toBe(a));
  it("resolves an id end", () => expect(linkEnd("a", byId)).toBe(a));
  it("is undefined for an unknown id", () => expect(linkEnd("zz", byId)).toBeUndefined());
});

describe("focus", () => {
  it("inCourseFocus: everything without a focused course, else only that course", () => {
    expect(inCourseFocus(c1, null)).toBe(true);
    expect(inCourseFocus(c1, "")).toBe(true);
    expect(inCourseFocus(c1, "c1")).toBe(true);
    expect(inCourseFocus(c1, "c2")).toBe(false);
  });

  it("hoverFocusId: the hovered id in legible mode only", () => {
    expect(hoverFocusId(true, { id: "a" })).toBe("a");
    expect(hoverFocusId(true, null)).toBeNull();
    expect(hoverFocusId(false, { id: "a" })).toBeNull();
  });

  it("hoverMastery: a course's average, a concept's score, 0 for nothing", () => {
    const avg = { Ling: 0.4 };
    expect(hoverMastery(null, avg)).toBe(0);
    expect(hoverMastery({ is_subject_root: true, subject: "Ling", mastery_score: 0.9 }, avg)).toBe(0.4);
    expect(hoverMastery({ is_subject_root: true, subject: "Math", mastery_score: 0.9 }, avg)).toBe(0);
    expect(hoverMastery({ subject: "Ling", mastery_score: 0.7 }, avg)).toBe(0.7);
    expect(hoverMastery({ subject: "Ling", mastery_score: NaN }, avg)).toBe(0);
  });
});

describe("link paint", () => {
  it("linkIncident: touches the focused concept at either end", () => {
    expect(linkIncident(null, "a", "b")).toBe(false);
    expect(linkIncident("a", "a", "b")).toBe(true);
    expect(linkIncident("b", "a", "b")).toBe(true);
    expect(linkIncident("c", "a", "b")).toBe(false);
  });

  it("plainLinkOpacity: mastery, constellation, the hand-drawn bar, otherwise", () => {
    expect(plainLinkOpacity(true, "constellation")).toBe(0.85);
    expect(plainLinkOpacity(true, "organism")).toBe(0.85);
    expect(plainLinkOpacity(false, "constellation")).toBe(0.35);
    expect(plainLinkOpacity(false, "organism")).toBe(0.45);
    expect(plainLinkOpacity(false, "orb")).toBe(0.2);
  });

  it("plainLinkOpacity: the course's own hand-drawn links stay faint in either colour mode", () => {
    // One to every starting concept: dozens of full-strength bars would bury the course.
    expect(plainLinkOpacity(false, "organism", true)).toBe(0.16);
    expect(plainLinkOpacity(true, "organism", true)).toBe(0.16);
    expect(plainLinkOpacity(false, "organism", false)).toBe(0.45);
    // The thin-line variants draw every link alike.
    expect(plainLinkOpacity(false, "orb", true)).toBe(0.2);
    expect(plainLinkOpacity(false, "constellation", true)).toBe(0.35);
    expect(plainLinkOpacity(true, "orb", true)).toBe(0.85);
    // …and such a link is thinner than the thinnest concept link.
    expect(ANCHOR_WIDTH).toBeLessThan(edgeWidthFor(0));
    expect(ANCHOR_WIDTH).toBeLessThan(edgeWidthFor(0.01));
  });

  it("legibleLinkOpacity: focus beats the course key, then anchor/mastery", () => {
    expect(legibleLinkOpacity(false, true, c1, c1, false, "a", null)).toBe(0.9);
    expect(legibleLinkOpacity(false, false, c1, c1, false, "a", null)).toBe(0.04);
    expect(legibleLinkOpacity(false, false, c1, c1, false, "a", "c2")).toBe(0.04);
    expect(legibleLinkOpacity(false, false, c1, c2, false, null, "c2")).toBe(0.03);
    expect(legibleLinkOpacity(false, false, c2, c1, false, null, "c2")).toBe(0.03);
    expect(legibleLinkOpacity(true, false, c1, c1, true, null, null)).toBe(0.1);
    expect(legibleLinkOpacity(undefined, false, c1, c1, true, null, "c1")).toBe(0.45);
    expect(legibleLinkOpacity(false, false, c1, c1, false, null, null)).toBe(0.16);
  });

  it("legibleLinkOpacity: a hand-drawn link rests brighter, and only at rest", () => {
    expect(legibleLinkOpacity(false, false, c1, c1, false, null, null, true)).toBe(0.26);
    // Focus, the course key, an anchor and mastery mode all still win.
    expect(legibleLinkOpacity(false, true, c1, c1, false, "a", null, true)).toBe(0.9);
    expect(legibleLinkOpacity(false, false, c1, c1, false, "a", null, true)).toBe(0.04);
    expect(legibleLinkOpacity(false, false, c1, c2, false, null, "c2", true)).toBe(0.03);
    expect(legibleLinkOpacity(true, false, c1, c1, false, null, null, true)).toBe(0.1);
    expect(legibleLinkOpacity(false, false, c1, c1, true, null, null, true)).toBe(0.45);
  });

  it("linkArrow: directed concept links in legible mode, when focused on or zoomed in", () => {
    const pre = { relationship_type: "prerequisite" as const };
    expect(linkArrow(pre, true, null, false, ARROW_ZOOM)).toBe(true);
    expect(linkArrow(pre, true, null, false, ARROW_ZOOM - 0.01)).toBe(false);
    expect(linkArrow(pre, true, null, false, 1)).toBe(true);
    expect(linkArrow(pre, true, "a", true, 0.1)).toBe(true);
    expect(linkArrow(pre, true, "a", false, 3)).toBe(false);
    expect(linkArrow(pre, false, null, false, 3)).toBe(false);
    expect(linkArrow({ ...pre, anchor: true }, true, null, false, 3)).toBe(false);
    expect(linkArrow({ relationship_type: "related" }, true, null, false, 3)).toBe(false);
    expect(linkArrow({}, true, null, false, 3)).toBe(false);
  });

  it("linkStroke and linkMarker", () => {
    expect(linkStroke(true, "g-e3", true)).toBe("url(#g-e3)");
    expect(linkStroke(false, "g-e3", true)).toBe("var(--text-dim)");
    expect(linkStroke(false, "g-e3", false)).toBe("var(--text-muted)");
    // A hand-drawn link is its course's one flat colour, focused or not;
    // mastery mode keeps its gradient.
    expect(linkStroke(false, "g-e3", false, "#3e6f8a")).toBe("#3e6f8a");
    expect(linkStroke(false, "g-e3", true, "#3e6f8a")).toBe("#3e6f8a");
    expect(linkStroke(true, "g-e3", false, "#3e6f8a")).toBe("url(#g-e3)");
    expect(linkMarker(false, "g", true)).toBeUndefined();
    expect(linkMarker(true, "g", true)).toBe("url(#g-arrow-on)");
    expect(linkMarker(true, "g", false)).toBe("url(#g-arrow)");
  });
});

describe("relatedDash", () => {
  it("is a row of round dots spaced by the link's width when hand-drawn", () => {
    expect(relatedDash(true, 3.6)).toBe("0.01 7.92");
    expect(relatedDash(true, 5)).toBe("0.01 11.00");
  });

  it("keeps the plain dash on a thin line, whatever its width", () => {
    expect(relatedDash(false, 3.6)).toBe("4 4");
    expect(relatedDash(false, 1.1)).toBe("4 4");
  });
});

describe("organicLinkSegment", () => {
  // The outline each end is cut at: the node's own, in the link's direction.
  const rim = (id: string, r: number, theta: number) => rimRadius(blobProfile(id, wobbleFor(r)), r, theta);
  // How far the arrowhead reaches past the line's end, plus a hair of air.
  const reach = (ARROW_SIZE * (10 - ARROW_REF_X)) / 10 + 1;

  it("runs from the source's drawn rim to the target's, half a unit under each", () => {
    const [x1, y1, x2, y2] = organicLinkSegment("a", 0, 0, 10, 10, "b", 100, 0, 12, 12, false);
    expect(y1).toBe(0);
    expect(y2).toBe(0);
    expect(x1).toBeCloseTo(rim("a", 10, 0) - 0.5, 10);
    expect(x2).toBeCloseTo(100 - (rim("b", 12, Math.PI) - 0.5), 10);
  });

  it("follows the outline, not the nominal radius", () => {
    // Around one node the link's start moves in and out with the wobble, so
    // the ends are not all the same distance from the centre.
    const starts = Array.from({ length: 12 }, (_, i) => {
      const theta = (i / 12) * Math.PI * 2;
      const [x1, y1] = organicLinkSegment("a", 0, 0, 10, 10, "b", 200 * Math.cos(theta), 200 * Math.sin(theta), 10, 10, false);
      return Math.hypot(x1, y1);
    });
    expect(Math.max(...starts) - Math.min(...starts)).toBeGreaterThan(0.3);
    // Every one stays within the wobble of the nominal radius.
    for (const d of starts) expect(Math.abs(d + 0.5 - 10)).toBeLessThanOrEqual(10 * wobbleFor(10) + 1e-9);
  });

  it("stops an arrowed link short of the target, leaving room for the head", () => {
    const plain = organicLinkSegment("a", 0, 0, 10, 10, "b", 100, 0, 12, 12, false);
    const arrowed = organicLinkSegment("a", 0, 0, 10, 10, "b", 100, 0, 12, 12, true);
    // The source end does not move.
    expect(arrowed[0]).toBe(plain[0]);
    expect(arrowed[2]).toBeCloseTo(100 - (rim("b", 12, Math.PI) + reach), 10);
    expect(plain[2] - arrowed[2]).toBeCloseTo(reach + 0.5, 10);
  });

  it("uses the resting radius for the shape and the drawn radius for the size", () => {
    // A node drawn larger than it rests (a hover, the quiz's growth) keeps its
    // outline: the same harmonics, scaled up.
    const [x1] = organicLinkSegment("a", 0, 0, 20, 10, "b", 200, 0, 10, 10, false);
    expect(x1).toBeCloseTo(rimRadius(blobProfile("a", wobbleFor(10)), 20, 0) - 0.5, 10);
  });

  it("draws nothing between nodes that touch or overlap", () => {
    expect(organicLinkSegment("a", 0, 0, 10, 10, "b", 15, 0, 10, 10, false)).toEqual([7.5, 0, 7.5, 0]);
    expect(organicLinkSegment("a", 4, 6, 10, 10, "b", 4, 6, 10, 10, true)).toEqual([4, 6, 4, 6]);
  });

  it("works along any direction", () => {
    const [x1, y1, x2, y2] = organicLinkSegment("a", 10, 20, 10, 10, "b", 10, 140, 10, 10, false);
    expect(x1).toBeCloseTo(10, 10);
    expect(x2).toBeCloseTo(10, 10);
    expect(y1).toBeCloseTo(20 + rim("a", 10, Math.PI / 2) - 0.5, 10);
    expect(y2).toBeCloseTo(140 - (rim("b", 10, -Math.PI / 2) - 0.5), 10);
  });
});

describe("node paint", () => {
  it("nodeOpacity: roots and mastery mode opaque, else the tier", () => {
    expect(nodeOpacity({ is_subject_root: true, mastery_tier: "struggling" }, false)).toBe(1);
    expect(nodeOpacity({ mastery_tier: "struggling" }, true)).toBe(1);
    expect(nodeOpacity({ mastery_tier: "struggling" }, false)).toBe(TIER_OPACITY.struggling);
  });

  it("isDragPinned: a concept with both fx and fy set", () => {
    expect(isDragPinned({ fx: 1, fy: 2 })).toBe(true);
    expect(isDragPinned({ fx: 0, fy: 0 })).toBe(true);
    expect(isDragPinned({ is_subject_root: true, fx: 1, fy: 2 })).toBe(false);
    expect(isDragPinned({ fx: 1, fy: null })).toBe(false);
    expect(isDragPinned({})).toBe(false);
  });

  it("nodeStrokeOpacity: pinned, hovered, resting", () => {
    expect(nodeStrokeOpacity(true, true)).toBe(1);
    expect(nodeStrokeOpacity(false, true)).toBe(0.9);
    expect(nodeStrokeOpacity(false, false)).toBe(NODE_STROKE_OPACITY);
  });

  it("nodeStrokeOpacity: a hand-drawn node has no rim at rest, one flat colour", () => {
    expect(nodeStrokeOpacity(false, false, true)).toBe(0);
    expect(nodeStrokeOpacity(false, true, true)).toBe(0.9);
    expect(nodeStrokeOpacity(true, false, true)).toBe(1);
  });

  it("legibleNodeOpacity: fades outside the hover focus, else outside the course key", () => {
    const focus = new Set(["a"]);
    const a = { id: "a", course_id: "c1" };
    const b = { id: "b", course_id: "c1" };
    expect(legibleNodeOpacity(a, "a", focus, "c2")).toBe(1);
    expect(legibleNodeOpacity(b, "a", focus, null)).toBe(0.15);
    expect(legibleNodeOpacity(b, null, focus, null)).toBe(1);
    expect(legibleNodeOpacity(b, null, focus, "c1")).toBe(1);
    expect(legibleNodeOpacity(b, null, focus, "c2")).toBe(0.15);
  });

  it("concept labels: size, weight and opacity", () => {
    expect(conceptLabelSize(false, true, 0.5)).toBe(10.5);
    expect(conceptLabelSize(true, false, 0.5)).toBe(10.5);
    expect(conceptLabelSize(true, true, 2)).toBe(10.5);
    expect(conceptLabelSize(true, true, 0.5)).toBe(21);
    expect(conceptLabelSize(true, true, 0.25)).toBe(24);
    expect(conceptLabelWeight(true, true)).toBe(600);
    expect(conceptLabelWeight(true, false)).toBeUndefined();
    expect(conceptLabelWeight(false, true)).toBeUndefined();
    expect(conceptLabelOpacity(false, "a", false, 0)).toBe(0.85);
    expect(conceptLabelOpacity(true, "a", true, 0)).toBe(0.85);
    expect(conceptLabelOpacity(true, "a", false, 1)).toBe(0);
    expect(conceptLabelOpacity(true, null, false, 0.5)).toBe(0.5 * 0.85);
  });
});
