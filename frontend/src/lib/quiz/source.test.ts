import { describe, expect, it } from "vitest";
import { buildQuizHref, isSafeReturnPath, parseEntry } from "./source";

function parse(query: string) {
  return parseEntry(new URLSearchParams(query));
}

describe("parseEntry — targets", () => {
  it("reads a concept deep link", () => {
    expect(parse("concept=node-1&from=tree&return=%2Ftree%3Fnode%3Dnode-1")).toEqual({
      concept: "node-1",
      source: { kind: "tree", returnTo: "/tree?node=node-1", conceptId: "node-1" },
    });
  });

  it("reads a topic (concept NAME) deep link", () => {
    expect(parse("topic=Recursion")).toEqual({
      topic: "Recursion",
      source: { kind: "link" },
    });
  });

  it("reads a course scope", () => {
    expect(parse("course=course-9&from=tree&return=%2Ftree")).toEqual({
      course: "course-9",
      source: { kind: "tree", returnTo: "/tree" },
    });
  });

  it("reads the due scope and ignores any other scope value", () => {
    expect(parse("scope=due&from=dashboard").scope).toBe("due");
    expect(parse("scope=everything").scope).toBeUndefined();
  });

  it("reads an attempt to resume", () => {
    expect(parse("attempt=a-1").attempt).toBe("a-1");
  });

  it("carries the note id from the notetaker", () => {
    expect(parse("concept=c1&from=notes&note=n7&return=%2Fnotetaker%3Fnote%3Dn7").source).toEqual({
      kind: "notes",
      returnTo: "/notetaker?note=n7",
      conceptId: "c1",
      noteId: "n7",
    });
  });
});

describe("parseEntry — source kind", () => {
  it("uses `from` when it names a known kind", () => {
    for (const kind of ["tree", "dashboard", "notes", "nav", "link", "quiz"]) {
      expect(parse(`from=${kind}`).source.kind).toBe(kind);
    }
  });

  it("treats a legacy deep link with no `from` as a link", () => {
    expect(parse("concept=c1").source.kind).toBe("link");
    expect(parse("topic=Recursion").source.kind).toBe("link");
  });

  it("treats a bare /quiz as nav", () => {
    expect(parse("").source.kind).toBe("nav");
  });

  it("falls back rather than trusting an unknown `from`", () => {
    expect(parse("from=evil&concept=c1").source.kind).toBe("link");
    expect(parse("from=evil").source.kind).toBe("nav");
  });

  it("ignores blank params", () => {
    // A whitespace-only concept is no target at all — the explicit `from` still
    // stands, but nothing is deep-linked and no conceptId lands on the source.
    expect(parse("concept=%20%20&from=tree")).toEqual({ source: { kind: "tree" } });
    expect(parse("concept=%20%20")).toEqual({ source: { kind: "nav" } });
  });
});

describe("isSafeReturnPath", () => {
  it("accepts a same-origin path", () => {
    expect(isSafeReturnPath("/tree")).toBe(true);
    expect(isSafeReturnPath("/tree?node=abc#x")).toBe(true);
  });

  it("rejects anything that could leave the origin", () => {
    expect(isSafeReturnPath("https://evil.com")).toBe(false);
    expect(isSafeReturnPath("//evil.com")).toBe(false);
    expect(isSafeReturnPath("/\\evil.com")).toBe(false);
    expect(isSafeReturnPath("javascript:alert(1)")).toBe(false);
    expect(isSafeReturnPath("tree")).toBe(false);
    expect(isSafeReturnPath("")).toBe(false);
    expect(isSafeReturnPath(null)).toBe(false);
    expect(isSafeReturnPath(undefined)).toBe(false);
  });

  it("rejects control characters that could hide the rest of the string", () => {
    expect(isSafeReturnPath("/tree\nhttps://evil.com")).toBe(false);
    expect(isSafeReturnPath("/tree\u0000")).toBe(false);
  });
});

describe("parseEntry — return safety", () => {
  it("drops an off-origin return rather than following it", () => {
    expect(parse("concept=c1&from=tree&return=https%3A%2F%2Fevil.com").source.returnTo)
      .toBeUndefined();
    expect(parse("concept=c1&from=tree&return=%2F%2Fevil.com").source.returnTo).toBeUndefined();
  });
});

describe("buildQuizHref", () => {
  it("builds the tree concept link from §6", () => {
    expect(
      buildQuizHref(
        { concept: "node-1" },
        { kind: "tree", returnTo: "/tree?node=node-1", conceptId: "node-1" },
      ),
    ).toBe("/quiz?concept=node-1&from=tree&return=%2Ftree%3Fnode%3Dnode-1");
  });

  it("builds the course link from a subject root", () => {
    expect(buildQuizHref({ course: "course-9" }, { kind: "tree", returnTo: "/tree" }))
      .toBe("/quiz?course=course-9&from=tree&return=%2Ftree");
  });

  it("builds the review-everything-due link", () => {
    expect(buildQuizHref({ scope: "due" }, { kind: "dashboard", returnTo: "/dashboard" }))
      .toBe("/quiz?scope=due&from=dashboard&return=%2Fdashboard");
  });

  it("builds the notetaker link, note id included", () => {
    expect(
      buildQuizHref(
        { concept: "c1" },
        { kind: "notes", returnTo: "/notetaker?note=n7", noteId: "n7" },
      ),
    ).toBe("/quiz?concept=c1&from=notes&return=%2Fnotetaker%3Fnote%3Dn7&note=n7");
  });

  it("builds a resume link", () => {
    expect(buildQuizHref({ attempt: "a-1" }, { kind: "quiz" })).toBe("/quiz?attempt=a-1&from=quiz");
  });

  it("refuses to encode an off-origin return", () => {
    const href = buildQuizHref({ concept: "c1" }, { kind: "tree", returnTo: "https://evil.com" });
    expect(href).toBe("/quiz?concept=c1&from=tree");
  });

  it("round-trips through parseEntry", () => {
    const source = { kind: "tree" as const, returnTo: "/tree?node=n1", conceptId: "n1" };
    const href = buildQuizHref({ concept: "n1" }, source);
    const entry = parseEntry(new URLSearchParams(href.slice(href.indexOf("?"))));
    expect(entry.concept).toBe("n1");
    expect(entry.source).toEqual(source);
  });
});

describe("the start marker", () => {
  it("is written only when asked for, after the source", () => {
    expect(buildQuizHref({ concept: "n1" }, { kind: "link", returnTo: "/study" }, { start: true }))
      .toBe("/quiz?concept=n1&from=link&return=%2Fstudy&start=1");
    expect(buildQuizHref({ concept: "n1" }, { kind: "link" })).toBe("/quiz?concept=n1&from=link");
  });

  it("round-trips through parseEntry, and only as `1`", () => {
    expect(parse("course=c1&from=link&start=1").start).toBe(true);
    expect(parse("course=c1&from=link&start=yes").start).toBeUndefined();
    expect(parse("course=c1&from=link").start).toBeUndefined();
  });
});
