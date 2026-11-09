import { describe, expect, it } from "vitest";
import type { EnrolledCourse } from "@/lib/api";
import type { Candidate } from "@/lib/quiz/proposals";
import type { AttemptSummary } from "@/lib/quiz/types";
import type { ResumableQuiz } from "@/lib/quiz/useQuizHome";
import type { GraphEdge, GraphNode } from "@/lib/types";
import {
  adjustSubtitle,
  arrivalQueue,
  candidateOf,
  cardCourseCode,
  cardDefinition,
  cardMeta,
  cardModeFor,
  cardRationale,
  cardTitle,
  conceptStartRequest,
  configLineFor,
  connectedCount,
  courseFilterFor,
  effectiveConfigFor,
  emptyTopicsCopy,
  entryKeyFor,
  filterTopicGroups,
  hiddenTopicFor,
  homeViewFor,
  pickedIdFor,
  pickTargetFor,
  prefsFor,
  queueStartRequest,
  resumeNameFor,
  resumeTotalFor,
  returnedIdFor,
  type Arrival,
} from "./homeView";

const CS: EnrolledCourse = {
  enrollment_id: "e-cs",
  course_id: "c-cs",
  course_code: "CS101",
  course_name: "Intro to Computer Science",
  school: "Test University",
  department: "TEST",
  color: "#7b4b99",
  nickname: null,
  node_count: 2,
  enrolled_at: "2026-01-01T00:00:00Z",
  term: "Spring 2026",
};
const MATH: EnrolledCourse = { ...CS, enrollment_id: "e-math", course_id: "c-math", course_code: "MATH210" };

function node(id: string, name: string, courseId = "c-cs"): GraphNode {
  return {
    id,
    concept_name: name,
    mastery_score: 0.3,
    mastery_tier: "struggling",
    times_studied: 0,
    last_studied_at: null,
    subject: "Intro to Computer Science",
    course_id: courseId,
    is_subject_root: false,
  };
}

function candidate(n: GraphNode, course: EnrolledCourse | null = CS): Candidate {
  return { node: n, course, color: "#7b4b99", rationale: "r" };
}

const REC = node("rec", "Recursion");
const DET = node("det", "Determinants", "c-math");

function arrival(over: Partial<Arrival> = {}): Arrival {
  return { conceptId: null, courseQueue: [], dueQueue: [], ...over };
}

const CFG = { count: 4, difficulty: "gentle", feedback: "at-end" as const };

describe("entryKeyFor / pickedIdFor", () => {
  it("keys an entry on its four arrival fields", () => {
    expect(entryKeyFor({ source: { kind: "nav" } })).toBe("|||");
    expect(entryKeyFor({ concept: "a", topic: "b", course: "c", scope: "due", source: { kind: "nav" } })).toBe(
      "a|b|c|due",
    );
  });

  it("keeps a pick only for its own arrival and a concept that still exists", () => {
    const nodes = [REC];
    expect(pickedIdFor(null, "k", nodes)).toBeNull();
    expect(pickedIdFor({ entryKey: "k", id: "rec" }, "k", nodes)).toBe("rec");
    expect(pickedIdFor({ entryKey: "other", id: "rec" }, "k", nodes)).toBeNull();
    expect(pickedIdFor({ entryKey: "k", id: "gone" }, "k", nodes)).toBeNull();
  });
});

describe("cardModeFor", () => {
  it("is a concept whenever something is picked or deep-linked", () => {
    expect(cardModeFor("rec", arrival({ course: "c-cs", courseQueue: ["rec"] }))).toBe("concept");
    expect(cardModeFor(null, arrival({ conceptId: "rec", scope: "due", dueQueue: ["rec"] }))).toBe("concept");
  });

  it("is a course queue, then the due set, when they have concepts", () => {
    expect(cardModeFor(null, arrival({ course: "c-cs", courseQueue: ["rec"] }))).toBe("course");
    expect(cardModeFor(null, arrival({ scope: "due", dueQueue: ["rec"] }))).toBe("due");
    // A course with nothing due falls through to the due set.
    expect(cardModeFor(null, arrival({ course: "c-x", scope: "due", dueQueue: ["rec"] }))).toBe("due");
    expect(cardModeFor(null, arrival({ course: "c-x" }))).toBe("concept");
    expect(cardModeFor(null, arrival({ scope: "due" }))).toBe("concept");
  });
});

describe("arrivalQueue", () => {
  it("names the queue the arrival proposes", () => {
    expect(arrivalQueue(arrival({ course: "c-cs", courseQueue: ["a"] }))).toEqual(["a"]);
    expect(arrivalQueue(arrival({ scope: "due", dueQueue: ["b"] }))).toEqual(["b"]);
  });

  it("is null for a deep link, an empty queue, or a course with nothing due", () => {
    expect(arrivalQueue(arrival({ conceptId: "x", course: "c-cs", courseQueue: ["a"] }))).toBeNull();
    expect(arrivalQueue(arrival({ course: "c-cs" }))).toBeNull();
    expect(arrivalQueue(arrival({ scope: "due" }))).toBeNull();
    // Unlike the card's mode, a `?course=` never falls through to the due set.
    expect(arrivalQueue(arrival({ course: "c-x", scope: "due", dueQueue: ["b"] }))).toBeNull();
  });
});

describe("candidateOf", () => {
  const ranked = candidate(REC);
  const home = { candidates: [ranked], nodes: [REC, DET], courses: [CS, MATH], attempts: [] as AttemptSummary[] };

  it("returns nothing for no id or an unknown one", () => {
    expect(candidateOf(null, home)).toBeNull();
    expect(candidateOf(undefined, home)).toBeNull();
    expect(candidateOf("gone", home)).toBeNull();
  });

  it("prefers the ranked candidate", () => {
    expect(candidateOf("rec", home)).toBe(ranked);
  });

  it("builds an unranked concept with its course and colour, and no last attempt", () => {
    const built = candidateOf("det", home);
    expect(built?.node).toBe(DET);
    expect(built?.course).toBe(MATH);
    expect(built?.color).toBe(MATH.color);
    expect(built).not.toHaveProperty("lastAttempt");
  });

  it("builds a concept outside every course with a null course", () => {
    const loose = node("loose", "Loose", "c-none");
    expect(candidateOf("loose", { ...home, nodes: [loose] })?.course).toBeNull();
  });
});

describe("the card's copy", () => {
  it("takes the course code off the entry for a course card, else off the card", () => {
    expect(cardCourseCode("course", MATH, candidate(REC))).toBe("MATH210");
    expect(cardCourseCode("concept", MATH, candidate(REC))).toBe("CS101");
    expect(cardCourseCode("due", null, candidate(REC, null))).toBe("");
    expect(cardCourseCode("course", null, candidate(REC))).toBe("");
    expect(cardCourseCode("concept", null, null)).toBe("");
  });

  it("titles each shape", () => {
    expect(cardTitle("course", "CS101", "Recursion")).toBe("Practice CS101");
    expect(cardTitle("due", "CS101", "Recursion")).toBe("Review everything due");
    expect(cardTitle("concept", "CS101", "Recursion")).toBe("Recursion");
  });

  it("writes each shape's meta line", () => {
    const due = { count: 7, courseCount: 2 } as Parameters<typeof cardMeta>[2];
    expect(cardMeta("course", 4, due, null)).toBe("4 concepts due");
    expect(cardMeta("due", 0, due, null)).toBe("7 concepts across 2 courses · starting with the 5 weakest");
    expect(cardMeta("due", 0, { ...due, count: 2 }, null)).toBe(
      "2 concepts across 2 courses · starting with the 2 weakest",
    );
    expect(cardMeta("concept", 0, due, candidate(REC))).toBe("30% · struggling · not studied yet");
    expect(cardMeta("concept", 0, due, null)).toBe("");
  });

  it("explains only an unpicked deep-linked concept card", () => {
    const card = candidate(REC);
    expect(cardRationale("concept", null, "rec", card, "tree")).toBe("From your tree");
    expect(cardRationale("concept", null, "rec", card, "notes")).toBe("From your note");
    expect(cardRationale("concept", null, "rec", card, "dashboard")).toBe("Suggested for you");
    expect(cardRationale("concept", "det", "rec", card, "tree")).toBeNull();
    expect(cardRationale("concept", null, null, card, "tree")).toBeNull();
    expect(cardRationale("concept", null, "rec", null, "tree")).toBeNull();
    expect(cardRationale("course", null, "rec", card, "tree")).toBeNull();
  });

  it("counts a concept's edges in either direction", () => {
    const edges: GraphEdge[] = [
      { id: "1", source: "rec", target: "a", strength: 1 },
      { id: "2", source: "b", target: "rec", strength: 1 },
      { id: "3", source: "a", target: "b", strength: 1 },
    ];
    expect(connectedCount(edges, "rec")).toBe(2);
    expect(connectedCount(edges, undefined)).toBe(0);
  });

  describe("cardDefinition", () => {
    const card = candidate(REC);
    const base = { cardConceptId: "rec", cardDescription: null, cardDescriptionPending: false, edges: [] };

    it("shows the hook's sentence when it describes this card", () => {
      expect(cardDefinition(false, card, { ...base, cardDescription: "Calling yourself." })).toEqual({
        definition: "Calling yourself.",
        pending: false,
      });
    });

    it("is pending while the fetch is in flight, or while the hook describes another card", () => {
      expect(cardDefinition(false, card, { ...base, cardDescriptionPending: true })).toEqual({
        definition: null,
        pending: true,
      });
      expect(cardDefinition(false, card, { ...base, cardConceptId: "det", cardDescription: "x" })).toEqual({
        definition: null,
        pending: true,
      });
    });

    it("falls back to the built sentence once the fetch has settled empty", () => {
      expect(cardDefinition(false, card, base)).toEqual({
        definition: "CS101 · struggling · 0 connected concepts",
        pending: false,
      });
    });

    it("shows nothing at all on a queued card", () => {
      expect(cardDefinition(true, card, { ...base, cardDescriptionPending: true })).toEqual({
        definition: null,
        pending: false,
      });
    });

    it("is pending with no card and no hook card", () => {
      expect(cardDefinition(false, null, { ...base, cardConceptId: null })).toEqual({
        definition: null,
        pending: true,
      });
    });
  });

  it("reads the config line per shape, with the feedback suffix", () => {
    expect(configLineFor(false, CFG)).toBe("4 questions, gentle");
    expect(configLineFor(true, CFG)).toBe("3 questions each, gentle");
    expect(configLineFor(false, { ...CFG, feedback: "as-you-go" })).toBe(
      "4 questions, gentle · answers as you go",
    );
  });

  it("runs a queue at the queue's count, and a concept on the session config itself", () => {
    expect(effectiveConfigFor(false, CFG)).toBe(CFG);
    expect(effectiveConfigFor(true, CFG)).toEqual({ ...CFG, count: 3 });
  });

  it("subtitles the adjust dialog with the course code when there is one", () => {
    expect(adjustSubtitle("Recursion", "CS101")).toBe("Recursion · CS101");
    expect(adjustSubtitle("Recursion", "")).toBe("Recursion");
  });

  it("remembers the three settings, and a question format when set", () => {
    expect(prefsFor(CFG)).toEqual(CFG);
    expect(prefsFor({ ...CFG, questionFormat: "mcq" })).toEqual({ ...CFG, questionFormat: "mcq" });
    expect(Object.keys(prefsFor({ ...CFG, questionFormat: "mcq" }))).toEqual([
      "count",
      "difficulty",
      "feedback",
      "questionFormat",
    ]);
  });
});

describe("start requests", () => {
  it("starts one concept as practice", () => {
    expect(conceptStartRequest(candidate(REC))).toEqual({
      intent: "practice",
      scope: { kind: "concept", conceptId: "rec" },
      conceptId: "rec",
      courseId: "c-cs",
    });
    expect(conceptStartRequest(candidate({ ...REC, course_id: undefined })).courseId).toBeNull();
  });

  it("starts a queue on its first concept", () => {
    const nodes = [REC, DET];
    expect(queueStartRequest("due", ["det", "rec"], nodes)).toEqual({
      intent: "review",
      scope: { kind: "due", queue: ["det", "rec"] },
      conceptId: "det",
      courseId: "c-math",
    });
    expect(queueStartRequest("course", ["rec"], nodes, "c-cs")).toEqual({
      intent: "practice",
      scope: { kind: "course", courseId: "c-cs", queue: ["rec"] },
      conceptId: "rec",
      courseId: "c-cs",
    });
    expect(queueStartRequest("course", ["gone"], nodes).scope).toEqual({
      kind: "course",
      courseId: "",
      queue: ["gone"],
    });
    expect(queueStartRequest("course", ["gone"], nodes).courseId).toBeNull();
  });
});

describe("swapping the card", () => {
  it("treats picking the suggested concept as going back, unless the suggestion is a queue", () => {
    expect(pickTargetFor("rec", false, "rec")).toBeNull();
    expect(pickTargetFor("rec", true, "rec")).toBe("rec");
    expect(pickTargetFor("det", false, "rec")).toBe("det");
    expect(pickTargetFor(null, false, "rec")).toBeNull();
  });

  it("points back at the outgoing concept only on a concept card that changed", () => {
    expect(returnedIdFor("concept", "rec", "det")).toBe("rec");
    expect(returnedIdFor("concept", "rec", "rec")).toBeNull();
    expect(returnedIdFor("course", "rec", "det")).toBeNull();
    expect(returnedIdFor("due", "rec", "det")).toBeNull();
    expect(returnedIdFor("concept", null, "det")).toBeNull();
  });
});

describe("the topic list", () => {
  const byCourse = [
    { course: CS, nodes: [REC, node("base", "Base cases")] },
    { course: MATH, nodes: [DET] },
  ];

  it("hides the card's concept only on an unsearched concept card", () => {
    expect(hiddenTopicFor("concept", "", candidate(REC))).toBe("rec");
    expect(hiddenTopicFor("concept", "rec", candidate(REC))).toBeUndefined();
    expect(hiddenTopicFor("course", "", candidate(REC))).toBeUndefined();
    expect(hiddenTopicFor("concept", "", null)).toBeUndefined();
  });

  it("falls back to every course when the narrowed one has gone", () => {
    expect(courseFilterFor(byCourse, "c-math")).toBe("c-math");
    expect(courseFilterFor(byCourse, "c-gone")).toBe("all");
    expect(courseFilterFor(byCourse, "all")).toBe("all");
  });

  it("filters by course, hidden concept, and a name or course-code query", () => {
    const ids = (groups: typeof byCourse) => groups.map(g => [g.course.course_id, g.nodes.map(n => n.id)]);
    expect(ids(filterTopicGroups(byCourse, "all", undefined, ""))).toEqual([
      ["c-cs", ["rec", "base"]],
      ["c-math", ["det"]],
    ]);
    expect(ids(filterTopicGroups(byCourse, "all", "rec", ""))).toEqual([
      ["c-cs", ["base"]],
      ["c-math", ["det"]],
    ]);
    expect(ids(filterTopicGroups(byCourse, "c-math", undefined, ""))).toEqual([["c-math", ["det"]]]);
    expect(ids(filterTopicGroups(byCourse, "all", undefined, "base"))).toEqual([["c-cs", ["base"]]]);
    expect(ids(filterTopicGroups(byCourse, "all", undefined, "math"))).toEqual([["c-math", ["det"]]]);
    // A group left empty disappears.
    expect(ids(filterTopicGroups(byCourse, "all", "det", "det"))).toEqual([]);
  });

  it("says why the list is empty", () => {
    expect(emptyTopicsCopy("  Zzz ", CS)).toBe("No concepts match “Zzz”");
    expect(emptyTopicsCopy("   ", CS)).toBe("Nothing else in CS101 yet");
    expect(emptyTopicsCopy("", undefined)).toBe("Nothing else on your tree yet");
  });
});

describe("regions", () => {
  it("names the arrival the screen renders, in priority order", () => {
    expect(homeViewFor("error", 0, 0)).toBe("error");
    expect(homeViewFor("loading", 2, 4)).toBe("loading");
    expect(homeViewFor("ready", 0, 4)).toBe("no-courses");
    expect(homeViewFor("ready", 2, 0)).toBe("empty-tree");
    expect(homeViewFor("ready", 2, 4)).toBe("home");
  });

  const resumable = (over: Partial<ResumableQuiz["attempt"]>): ResumableQuiz => ({
    attempt: {
      quiz_id: "q1",
      status: "in_progress",
      resumable: true,
      difficulty: "gentle",
      concept_node_id: "rec",
      questions: [],
      responses: [],
      score: null,
      total: null,
      created_at: "2026-08-22T00:00:00Z",
      ...over,
    },
    session: null,
    answered: 0,
  });

  it("names a resumable attempt off the tree, then the history, then generically", () => {
    const attempts = [{ quiz_id: "q1", concept_name: "From history" } as AttemptSummary];
    expect(resumeNameFor(resumable({}), [REC], attempts)).toBe("Recursion");
    expect(resumeNameFor(resumable({ concept_node_id: "gone" }), [REC], attempts)).toBe("From history");
    expect(resumeNameFor(resumable({ concept_node_id: "gone" }), [REC], [])).toBe("a concept");
  });

  it("totals a resumable attempt off its questions, then its total, then zero", () => {
    const q = { id: 1, question: "Q", options: [], difficulty: "gentle" };
    expect(resumeTotalFor(resumable({ questions: [q, q], total: 9 }))).toBe(2);
    expect(resumeTotalFor(resumable({ total: 9 }))).toBe(9);
    expect(resumeTotalFor(resumable({}))).toBe(0);
  });
});
