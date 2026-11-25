import { describe, expect, it } from "vitest";

import type { EnrolledCourse } from "@/lib/api";
import type { DocFolder, Document as Doc } from "@/lib/types";

import {
  addedLabel, dedupeCourses, filterDocuments, fmtOf, foldersAtLoc, highlight,
  parseLoc, timeOf, titleOf, uniqueName, type Loc,
} from "./libraryModel";

const course = (id: string, code: string, name = code): EnrolledCourse => ({
  enrollment_id: `enr-${id}`, course_id: id, course_code: code, course_name: name,
  color: null,
} as EnrolledCourse);

const COURSES = [course("c1", "CS101", "Intro to CS"), course("c2", "MA225", "Calculus")];

const doc = (over: Partial<Doc> & { id: string }): Doc => ({
  user_id: "u1",
  course_id: null,
  file_name: `${over.id}.pdf`,
  category: "reading",
  summary: null,
  concept_notes: null,
  created_at: "2026-04-01T00:00:00Z",
  processed_at: null,
  ...over,
});

const folder = (id: string, name: string, course_id: string | null): DocFolder => ({
  id, user_id: "u1", course_id, name,
  created_at: "2026-04-01T00:00:00Z", updated_at: "2026-04-01T00:00:00Z",
});

const run = (over: Partial<Parameters<typeof filterDocuments>[0]>) => filterDocuments({
  docs: [], loc: "all" as Loc, q: "", type: "all", sort: "recent",
  folders: [], courses: COURSES, ...over,
});

describe("titleOf / fmtOf", () => {
  it("shows the name without its extension, and tags the format", () => {
    const d = doc({ id: "a", file_name: "Determinants Lecture 7.pdf" });
    expect(titleOf(d)).toBe("Determinants Lecture 7");
    expect(fmtOf(d)).toBe("PDF");
    expect(fmtOf(doc({ id: "b", file_name: "slides.pptx" }))).toBe("PPTX");
    expect(fmtOf(doc({ id: "c", file_name: "notes.docx" }))).toBe("DOCX");
  });

  it("falls back to PDF for a name with no usable extension", () => {
    expect(fmtOf(doc({ id: "d", file_name: "Scan 0412" }))).toBe("PDF");
  });
});

describe("highlight", () => {
  it("splits around the first case-insensitive match", () => {
    expect(highlight("Determinants", "term")).toEqual({ a: "De", m: "term", b: "inants" });
  });

  it("returns the whole string when nothing matches", () => {
    expect(highlight("Determinants", "zzz")).toEqual({ a: "Determinants", m: "", b: "" });
    expect(highlight("Determinants", "")).toEqual({ a: "Determinants", m: "", b: "" });
  });
});

describe("uniqueName", () => {
  it("keeps the base when it is free, then counts up", () => {
    expect(uniqueName("New Folder", [])).toBe("New Folder");
    expect(uniqueName("New Folder", ["New Folder"])).toBe("New Folder 2");
    expect(uniqueName("New Folder", ["New Folder", "New Folder 2"])).toBe("New Folder 3");
  });
});

describe("dedupeCourses", () => {
  it("keeps one row per abstract course, the first enrollment's (#449)", () => {
    const twice = [
      { ...course("c1", "CS101"), enrollment_id: "fall" },
      { ...course("c1", "CS101"), enrollment_id: "spring" },
      course("c2", "MA225"),
    ] as EnrolledCourse[];
    const out = dedupeCourses(twice);
    expect(out).toHaveLength(2);
    expect(out[0].enrollment_id).toBe("fall");
  });
});

describe("parseLoc", () => {
  it("reads each location shape", () => {
    expect(parseLoc("all")).toEqual({ kind: "all", id: null });
    expect(parseLoc("trash")).toEqual({ kind: "trash", id: null });
    expect(parseLoc("c:c1")).toEqual({ kind: "c", id: "c1" });
    expect(parseLoc("f:f1")).toEqual({ kind: "f", id: "f1" });
  });
});

describe("filterDocuments: scope", () => {
  const docs = [
    doc({ id: "a", course_id: "c1" }),
    doc({ id: "b", course_id: "c1", folder_id: "f1" }),
    doc({ id: "c", course_id: "c2" }),
    doc({ id: "d" }),
  ];
  const folders = [folder("f1", "Midterm Prep", "c1")];

  it("All Documents shows everything, folders included", () => {
    expect(run({ docs, folders }).list.map(d => d.id).sort()).toEqual(["a", "b", "c", "d"]);
  });

  it("a course root hides the documents that are inside its folders", () => {
    const { list } = run({ docs, folders, loc: "c:c1" });
    expect(list.map(d => d.id)).toEqual(["a"]);
  });

  it("a folder shows exactly its own documents", () => {
    expect(run({ docs, folders, loc: "f:f1" }).list.map(d => d.id)).toEqual(["b"]);
  });

  it("No Course is the documents with no course", () => {
    expect(run({ docs, folders, loc: "c:none" }).list.map(d => d.id)).toEqual(["d"]);
  });

  it("a search inside a course reaches into its folders", () => {
    // With a query running, the course root stops hiding foldered documents,
    // so a search never misses something filed away.
    const { list } = run({ docs, folders, loc: "c:c1", q: "b" });
    expect(list.map(d => d.id)).toEqual(["b"]);
  });
});

describe("filterDocuments: search", () => {
  const docs = [
    doc({ id: "a", file_name: "Recursion Workshop.pdf" }),
    doc({ id: "b", file_name: "Lab 4.pdf", summary: "Walk an array three ways." }),
    doc({
      id: "c", file_name: "Lecture.pdf",
      concept_notes: [{ name: "Eigenvalues", description: "" }],
    }),
    doc({ id: "d", file_name: "Reading.pdf", course_id: "c2" }),
  ];

  it("matches a title, a summary, a concept, or the course code", () => {
    expect(run({ docs, q: "recursion" }).list.map(d => d.id)).toEqual(["a"]);
    expect(run({ docs, q: "array" }).list.map(d => d.id)).toEqual(["b"]);
    expect(run({ docs, q: "eigen" }).list.map(d => d.id)).toEqual(["c"]);
    expect(run({ docs, q: "ma225" }).list.map(d => d.id)).toEqual(["d"]);
  });

  it("matches nothing it should not", () => {
    expect(run({ docs, q: "zzz" }).list).toEqual([]);
  });
});

describe("filterDocuments: type filter and its counts", () => {
  const docs = [
    doc({ id: "a", category: "lecture_notes" }),
    doc({ id: "b", category: "lecture_notes" }),
    doc({ id: "c", category: "slides" }),
  ];

  it("`scoped` ignores the type filter so the Type menu's counts stay honest", () => {
    const { scoped, list } = run({ docs, type: "slides" });
    expect(list.map(d => d.id)).toEqual(["c"]);
    expect(scoped).toHaveLength(3);
  });
});

describe("filterDocuments: sort", () => {
  const docs = [
    doc({
      id: "old", file_name: "Zeta.pdf", created_at: "2026-01-01T00:00:00Z",
      page_count: 2, category: "slides", course_id: "c2",
    }),
    doc({
      id: "new", file_name: "Alpha.pdf", created_at: "2026-06-01T00:00:00Z",
      page_count: 30, category: "assignment", course_id: "c1",
    }),
    doc({
      id: "mid", file_name: "Mu.pdf", created_at: "2026-03-01T00:00:00Z",
      category: "lecture_notes",
    }),
  ];
  const ids = (sort: Parameters<typeof run>[0]["sort"]) =>
    run({ docs, sort }).list.map(d => d.id);

  it("orders by date, name, pages, type and course", () => {
    expect(ids("recent")).toEqual(["new", "mid", "old"]);
    expect(ids("oldest")).toEqual(["old", "mid", "new"]);
    expect(ids("name")).toEqual(["new", "mid", "old"]);
    // An unknown page count is not zero: it sorts last.
    expect(ids("pages")).toEqual(["new", "old", "mid"]);
    expect(ids("type")).toEqual(["new", "mid", "old"]);
    // No course sorts after every real course code.
    expect(ids("course")).toEqual(["new", "old", "mid"]);
  });
});

describe("foldersAtLoc", () => {
  const folders = [
    folder("f1", "Midterm Prep", "c1"),
    folder("f2", "Loose", null),
  ];

  it("shows a course's folders only at that course's root", () => {
    expect(foldersAtLoc(folders, "c:c1", "").map(f => f.id)).toEqual(["f1"]);
    expect(foldersAtLoc(folders, "c:none", "").map(f => f.id)).toEqual(["f2"]);
    expect(foldersAtLoc(folders, "all", "")).toEqual([]);
    expect(foldersAtLoc(folders, "f:f1", "")).toEqual([]);
  });

  it("hides them while a search is running, so results are documents", () => {
    expect(foldersAtLoc(folders, "c:c1", "mid")).toEqual([]);
  });
});

describe("timeOf / addedLabel", () => {
  it("degrade rather than throw on an unreadable date", () => {
    expect(timeOf(doc({ id: "x", created_at: "nonsense" }))).toBe(0);
    expect(addedLabel("nonsense")).toBe("—");
  });

  it("reads a real date", () => {
    expect(timeOf(doc({ id: "x", created_at: "2026-04-01T00:00:00Z" }))).toBeGreaterThan(0);
    expect(addedLabel("2026-04-01T12:00:00Z")).toMatch(/Apr/);
  });
});
