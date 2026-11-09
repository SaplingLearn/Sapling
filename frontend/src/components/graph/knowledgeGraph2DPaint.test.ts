import { describe, expect, it } from "vitest";
import { NODE_STROKE_OPACITY, TIER_OPACITY } from "@/lib/graph/nodeStyle";
import {
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
  plainLinkOpacity,
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

  it("plainLinkOpacity: mastery, constellation, otherwise", () => {
    expect(plainLinkOpacity(true, "constellation")).toBe(0.85);
    expect(plainLinkOpacity(false, "constellation")).toBe(0.35);
    expect(plainLinkOpacity(false, "organism")).toBe(0.2);
    expect(plainLinkOpacity(false, "orb")).toBe(0.2);
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

  it("linkArrow: directed concept links in legible mode, when focused on or zoomed in", () => {
    const pre = { relationship_type: "prerequisite" as const };
    expect(linkArrow(pre, true, null, false, 0.9)).toBe(true);
    expect(linkArrow(pre, true, null, false, 0.89)).toBe(false);
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
    expect(linkMarker(false, "g", true)).toBeUndefined();
    expect(linkMarker(true, "g", true)).toBe("url(#g-arrow-on)");
    expect(linkMarker(true, "g", false)).toBe("url(#g-arrow)");
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
