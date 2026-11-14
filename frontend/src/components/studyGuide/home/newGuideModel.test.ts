import { describe, expect, it } from "vitest";

import type { MaterialOption, ScopeOption } from "@/lib/studyGuide/types";

import {
  DEFAULT_DEPTH,
  DEFAULT_GOAL,
  DEPTH_OPTIONS,
  GOAL_OPTIONS,
  MAX_MATERIALS,
  allIds,
  atCap,
  buildRequest,
  canGenerate,
  findScope,
  inListOrder,
  scopeKey,
  scopeNote,
  suggestedIds,
  toggleId,
  withNewMaterials,
  type GuideForm,
} from "./newGuideModel";

const material = (id: string): MaterialOption => ({ id, file_name: `${id}.pdf`, category: "slides", created_at: "2026-11-01T00:00:00Z" });
const many = (n: number) => Array.from({ length: n }, (_, i) => material(`d${i + 1}`));

const COURSE: ScopeOption = { kind: "course", id: null, title: "Whole course", due_date: null, suggested_material_ids: ["d1", "d2", "gone"] };
const EXAM: ScopeOption = { kind: "exam", id: "e1", title: "Midterm 2", due_date: "2026-11-21", suggested_material_ids: ["d2"] };
const LAB: ScopeOption = { kind: "assignment", id: "a1", title: "Lab 5", due_date: "2026-11-18T23:59:00Z", suggested_material_ids: [] };

const form = (over: Partial<GuideForm> = {}): GuideForm => ({
  courseId: "c1", semester: "Fall 2026", scope: EXAM, goal: "exam_prep", depth: "standard",
  materialIds: ["d1", "d2"], useHistory: true, ...over,
});

describe("defaults and options", () => {
  it("starts on Exam prep and Standard", () => {
    expect(DEFAULT_GOAL).toBe("exam_prep");
    expect(DEFAULT_DEPTH).toBe("standard");
  });

  it("offers the three goals and the three depths, in the spec's order", () => {
    expect(GOAL_OPTIONS).toEqual([
      { value: "practice", label: "Practice" },
      { value: "review", label: "Review" },
      { value: "exam_prep", label: "Exam prep" },
    ]);
    expect(DEPTH_OPTIONS).toEqual([
      { value: "cram", label: "Cram sheet" },
      { value: "standard", label: "Standard" },
      { value: "deep", label: "Deep review" },
    ]);
  });
});

describe("scopes", () => {
  it("keys a scope by its kind and id, the whole course by its kind alone", () => {
    expect(scopeKey(COURSE)).toBe("course");
    expect(scopeKey(EXAM)).toBe("exam:e1");
    expect(scopeKey(LAB)).toBe("assignment:a1");
  });

  it("finds a scope by its key", () => {
    expect(findScope([COURSE, EXAM, LAB], "exam:e1")).toBe(EXAM);
    expect(findScope([COURSE, EXAM, LAB], "exam:nope")).toBeNull();
    expect(findScope([], "")).toBeNull();
  });

  it("notes what a scope is, and its due date when it has one", () => {
    expect(scopeNote(COURSE)).toBe("Whole course");
    expect(scopeNote(EXAM)).toBe("Exam · due Sat, Nov 21");
    expect(scopeNote(LAB)).toBe("Assignment · due Wed, Nov 18");
    expect(scopeNote({ ...EXAM, due_date: "soon" })).toBe("Exam");
  });
});

describe("the selection", () => {
  it("pre-selects a scope's suggested materials that the class still has", () => {
    expect(suggestedIds(COURSE, many(3))).toEqual(["d1", "d2"]);
    expect(suggestedIds(EXAM, many(3))).toEqual(["d2"]);
    expect(suggestedIds(null, many(3))).toEqual([]);
  });

  it("never selects more than the cap, and past it leaves out the oldest", () => {
    // A class lists its materials oldest first: d1 is the oldest, d35 the newest.
    const materials = many(MAX_MATERIALS + 5);
    const newest = materials.slice(5).map(m => m.id);
    const everything = { ...COURSE, suggested_material_ids: materials.map(m => m.id) };
    expect(suggestedIds(everything, materials)).toEqual(newest);
    expect(allIds(materials)).toEqual(newest);
    expect(allIds(materials)).toHaveLength(MAX_MATERIALS);
    expect(allIds(many(2))).toEqual(["d1", "d2"]);
  });

  it("toggles a tile on and off", () => {
    expect(toggleId(["d1"], "d2")).toEqual(["d1", "d2"]);
    expect(toggleId(["d1", "d2"], "d1")).toEqual(["d2"]);
  });

  it("at the cap, turns a tile off but not on", () => {
    const full = allIds(many(MAX_MATERIALS));
    expect(atCap(full)).toBe(true);
    expect(atCap(full.slice(1))).toBe(false);
    expect(toggleId(full, "extra")).toBe(full);
    expect(toggleId(full, "d1")).toHaveLength(MAX_MATERIALS - 1);
  });

  it("adds the materials an upload brought, and drops ones the class lost", () => {
    const before = [material("d1"), material("d2")];
    const after = [material("d2"), material("d3"), material("d4")];
    expect(withNewMaterials(["d1", "d2"], before, after)).toEqual(["d2", "d3", "d4"]);
    expect(withNewMaterials([], before, before)).toEqual([]);
  });

  it("keeps the cap when an upload would pass it, leaving out the oldest", () => {
    const before = many(MAX_MATERIALS);
    const after = [...before, material("new")];
    expect(withNewMaterials(allIds(before), before, after)).toEqual([...allIds(before).slice(1), "new"]);
  });

  it("leaves out the oldest past the cap whatever order the tiles were picked in", () => {
    const before = many(MAX_MATERIALS);
    const after = [...before, material("new")];
    const picked = [...allIds(before)].reverse();
    expect(withNewMaterials(picked, before, after)).toEqual([...allIds(before).slice(1), "new"]);
  });

  it("orders the picked ids as the class lists its materials", () => {
    expect(inListOrder(["d3", "d1", "gone"], many(3))).toEqual(["d1", "d3"]);
  });
});

describe("the request", () => {
  it("needs a class and at least one material", () => {
    expect(canGenerate(form())).toBe(true);
    expect(canGenerate(form({ courseId: "" }))).toBe(false);
    expect(canGenerate(form({ materialIds: [] }))).toBe(false);
  });

  it("is the choices, field for field", () => {
    expect(buildRequest(form({ goal: "review", depth: "deep", useHistory: false }))).toEqual({
      course_id: "c1",
      semester: "Fall 2026",
      scope_kind: "exam",
      scope_id: "e1",
      goal: "review",
      depth: "deep",
      material_ids: ["d1", "d2"],
      use_history: false,
    });
  });

  it("sends the whole course with no scope id, and no term as null", () => {
    expect(buildRequest(form({ scope: COURSE, semester: "" }))).toMatchObject({
      semester: null, scope_kind: "course", scope_id: null,
    });
    expect(buildRequest(form({ scope: null }))).toMatchObject({ scope_kind: "course", scope_id: null });
  });
});
