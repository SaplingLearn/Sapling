import { describe, it, expect } from "vitest";
import type { EnrolledCourse } from "@/lib/api";
import { flashcardsHref } from "@/lib/toolHrefs";
import {
  courseAccent,
  courseLabel,
  headerPlace,
  importTopic,
  opensBuilder,
  pageGates,
  pageView,
  parseArrival,
  startBlocked,
  type Arrival,
  type OpenReview,
  type PageLoads,
} from "./pageModel";

const arrival = (over: Partial<Arrival> = {}): Arrival =>
  ({ courseId: "c1", concepts: ["Recursion"], start: false, review: false, build: false, ...over });

const LOADED: PageLoads = {
  cardsLoaded: true, cardsLoading: false, cardsFailed: false,
  coursesReady: true, coursesFailed: false, mapReady: true, setsSettled: true,
};

const review = (from: OpenReview["from"]): OpenReview => ({ deck: [], title: "Midterm", from });

describe("parseArrival", () => {
  it("reads the course, the concepts and the markers", () => {
    const params = new URLSearchParams("course=c1&concepts=A| B ||C&start=1&review=1&build=1");
    expect(parseArrival(params, true)).toEqual({ courseId: "c1", concepts: ["A", "B", "C"], start: true, review: true, build: true });
  });

  it("reads a concept name that holds the separator, as the hub writes it", () => {
    const href = flashcardsHref("c1", ["Read | Write", "AT&T, 100%"]);
    const params = new URL(href, "http://x").searchParams;
    expect(parseArrival(params, false).concepts).toEqual(["Read | Write", "AT&T, 100%"]);
  });

  it("a bare URL asks for nothing", () => {
    expect(parseArrival(new URLSearchParams(""), true)).toEqual({ courseId: "", concepts: [], start: false, review: false, build: false });
  });

  it("start counts only while the live URL still says so", () => {
    expect(parseArrival(new URLSearchParams("start=1"), false).start).toBe(false);
    expect(parseArrival(new URLSearchParams("start=yes"), true).start).toBe(false);
  });
});

describe("what a link opens", () => {
  it("concepts without start open the builder", () => {
    expect(opensBuilder(arrival())).toBe(true);
    expect(opensBuilder(arrival({ start: true }))).toBe(false);
    expect(opensBuilder(arrival({ concepts: [] }))).toBe(false);
  });

  it("start is blocked with nothing named, an unread deck, or another course than the link's", () => {
    expect(startBlocked(arrival(), "c1", false)).toBe(false);
    expect(startBlocked(arrival({ concepts: [] }), "c1", false)).toBe(true);
    expect(startBlocked(arrival(), "c1", true)).toBe(true);
    expect(startBlocked(arrival(), "c2", false)).toBe(true);
    // A link with no course starts on whatever course the page is on.
    expect(startBlocked(arrival({ courseId: "" }), "c2", false)).toBe(false);
  });
});

describe("pageGates", () => {
  it("everything loaded: every gate is open and nothing failed", () => {
    expect(pageGates(arrival(), LOADED)).toMatchObject({ start: true, restoreReview: true, home: true, failed: false });
  });

  it("start waits for the cards, and for the course list only when the link names a course", () => {
    expect(pageGates(arrival(), { ...LOADED, cardsLoading: true }).start).toBe(false);
    expect(pageGates(arrival(), { ...LOADED, coursesReady: false }).start).toBe(false);
    expect(pageGates(arrival({ courseId: "" }), { ...LOADED, coursesReady: false }).start).toBe(true);
  });

  it("a review is read back only once the course is known and the cards were really read", () => {
    expect(pageGates(arrival({ courseId: "" }), { ...LOADED, coursesReady: false }).restoreReview).toBe(false);
    expect(pageGates(arrival(), { ...LOADED, cardsFailed: true }).restoreReview).toBe(false);
    expect(pageGates(arrival(), { ...LOADED, cardsLoading: true }).restoreReview).toBe(false);
  });

  it("the home waits on all four reads", () => {
    for (const key of ["cardsLoaded", "coursesReady", "mapReady", "setsSettled"] as const) {
      expect(pageGates(arrival(), { ...LOADED, [key]: false }).home).toBe(false);
    }
  });

  it("either list failing is a failure", () => {
    expect(pageGates(arrival(), { ...LOADED, cardsFailed: true }).failed).toBe(true);
    expect(pageGates(arrival(), { ...LOADED, coursesFailed: true }).failed).toBe(true);
  });

  it("start=1 outranks the reload markers", () => {
    expect(pageGates(arrival({ review: true, build: true }), LOADED)).toMatchObject({ wantsReview: true, wantsBuild: true });
    expect(pageGates(arrival({ review: true, build: true, start: true }), LOADED)).toMatchObject({ wantsReview: false, wantsBuild: false });
  });
});

describe("pageView", () => {
  const base = { review: null, failed: false, arriving: false, ready: true, build: null };

  it("an open review shows over everything", () => {
    const open = review("home");
    expect(pageView({ ...base, review: open, failed: true, arriving: true, build: { note: "" } })).toEqual({ kind: "review", review: open });
  });

  it("then a failed load, then an arrival, then loading", () => {
    expect(pageView({ ...base, failed: true, arriving: true, ready: false }).kind).toBe("failed");
    expect(pageView({ ...base, arriving: true, ready: false }).kind).toBe("arriving");
    expect(pageView({ ...base, ready: false, build: { note: "" } }).kind).toBe("loading");
  });

  it("else the builder when it is open, else the home", () => {
    expect(pageView({ ...base, build: { note: "Sorted 2" } })).toEqual({ kind: "build", build: { note: "Sorted 2" } });
    expect(pageView(base)).toEqual({ kind: "home" });
  });
});

describe("the header", () => {
  const draft = { setId: null, givenName: null };

  it("a review names its deck; one started in the builder goes back to the selection", () => {
    expect(headerPlace({ kind: "review", review: review("home") }, draft)).toEqual({ label: "Midterm", back: "All sets" });
    expect(headerPlace({ kind: "review", review: review("link") }, draft)).toEqual({ label: "Midterm", back: "All sets" });
    expect(headerPlace({ kind: "review", review: review("build") }, draft))
      .toEqual({ label: "Midterm", back: "Back", backLabel: "Back to your selection" });
  });

  it("the builder names the set being edited, or a new one", () => {
    const view = { kind: "build", build: { note: "" } } as const;
    expect(headerPlace(view, draft)?.label).toBe("New set");
    expect(headerPlace(view, { setId: "s1", givenName: "Week 3" })?.label).toBe("Week 3");
    expect(headerPlace(view, { setId: "s1", givenName: null })?.label).toBe("Edit set");
  });

  it("every other state keeps the course field", () => {
    for (const kind of ["home", "loading", "arriving", "failed"] as const) {
      expect(headerPlace({ kind }, draft)).toBeNull();
    }
  });

  it("Import opens on the one ticked concept", () => {
    expect(importTopic({ selected: ["Recursion"] })).toBe("Recursion");
    expect(importTopic({ selected: [] })).toBe("");
    expect(importTopic({ selected: ["A", "B"] })).toBe("");
  });
});

describe("the course", () => {
  const course = { course_code: "CS101", course_name: "Intro to CS", color: "#123456" } as EnrolledCourse;

  it("is called by its code, else its name, else nothing", () => {
    expect(courseLabel(course)).toBe("CS101");
    expect(courseLabel({ ...course, course_code: "" })).toBe("Intro to CS");
    expect(courseLabel(undefined)).toBe("");
  });

  it("lends the review its colour, else the brand's", () => {
    expect(courseAccent(course)).toBe("#123456");
    expect(courseAccent({ ...course, color: null })).toBe("var(--brand-forest)");
    expect(courseAccent(undefined)).toBe("var(--brand-forest)");
  });
});
