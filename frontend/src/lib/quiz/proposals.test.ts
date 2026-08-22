import { describe, expect, it } from "vitest";
import type { EnrolledCourse } from "@/lib/api";
import type { GraphNode } from "@/lib/types";
import {
  DUE_TIERS,
  alternativesOf,
  colorFor,
  dueSet,
  groupByCourse,
  isDue,
  latestCompletedAttempt,
  metaLine,
  primaryOf,
  queueFor,
  rankCandidates,
  rationaleFor,
} from "./proposals";
import { QUEUE_MAX } from "./session";
import type { AttemptSummary } from "./types";

const NOW = new Date(2026, 7, 22, 9); // 22 Aug 2026, local

function node(over: Partial<GraphNode> & { id: string }): GraphNode {
  return {
    concept_name: over.id,
    mastery_score: 0.3,
    mastery_tier: "struggling",
    times_studied: 1,
    last_studied_at: null,
    subject: "CS",
    course_id: "course-a",
    ...over,
  };
}

function course(over: Partial<EnrolledCourse> & { course_id: string }): EnrolledCourse {
  return {
    enrollment_id: `e-${over.course_id}`,
    course_code: "CS 101",
    course_name: "Intro",
    school: "BU",
    department: "CS",
    color: "#123456",
    nickname: null,
    node_count: 0,
    enrolled_at: "2026-01-01T00:00:00Z",
    term: "Fall 2026",
    ...over,
  };
}

function attempt(over: Partial<AttemptSummary> & { quiz_id: string; concept_node_id: string }): AttemptSummary {
  return {
    status: "completed",
    concept_name: over.concept_node_id,
    course_id: "course-a",
    score: 2,
    total: 5,
    difficulty: "medium",
    mastery_before: 0.2,
    mastery_after: 0.26,
    mastery_delta: 0.06,
    created_at: "2026-08-20T10:00:00Z",
    completed_at: "2026-08-20T10:05:00Z",
    ...over,
  };
}

function iso(y: number, m: number, d: number): string {
  return new Date(y, m - 1, d, 12).toISOString();
}

describe("isDue — the mirrored membership filter", () => {
  it("matches the three tiers get_recommendations asks for", () => {
    expect(DUE_TIERS).toEqual(["struggling", "learning", "unexplored"]);
    for (const tier of DUE_TIERS) {
      expect(isDue(node({ id: "n", mastery_tier: tier as GraphNode["mastery_tier"] }))).toBe(true);
    }
  });

  it("excludes mastered and subject roots", () => {
    expect(isDue(node({ id: "n", mastery_tier: "mastered" }))).toBe(false);
    expect(isDue(node({ id: "n", mastery_tier: "subject_root" }))).toBe(false);
    expect(isDue(node({ id: "n", mastery_tier: "struggling", is_subject_root: true }))).toBe(false);
  });
});

describe("rankCandidates", () => {
  const nodes = [
    node({ id: "n-mid", mastery_score: 0.44, mastery_tier: "learning" }),
    node({ id: "n-mastered", mastery_score: 0.9, mastery_tier: "mastered" }),
    node({ id: "n-new", mastery_score: 0, mastery_tier: "unexplored", times_studied: 0 }),
    node({ id: "n-low", mastery_score: 0.12, mastery_tier: "struggling" }),
    node({ id: "n-root", mastery_tier: "subject_root", is_subject_root: true }),
  ];

  it("orders by mastery ascending, mastered and roots dropped", () => {
    const ranked = rankCandidates(nodes, [], [], NOW);
    expect(ranked.map(c => c.node.id)).toEqual(["n-new", "n-low", "n-mid"]);
  });

  it("breaks ties deterministically so cards never reshuffle", () => {
    const tied = [
      node({ id: "b", mastery_score: 0.2 }),
      node({ id: "a", mastery_score: 0.2 }),
    ];
    expect(rankCandidates(tied, [], [], NOW).map(c => c.node.id)).toEqual(["a", "b"]);
    expect(rankCandidates(tied.slice().reverse(), [], [], NOW).map(c => c.node.id))
      .toEqual(["a", "b"]);
  });

  it("does not mutate the caller's node array", () => {
    const input = nodes.slice();
    rankCandidates(input, [], [], NOW);
    expect(input.map(n => n.id)).toEqual(nodes.map(n => n.id));
  });

  it("joins the course, the colour and the last completed attempt", () => {
    const courses = [course({ course_id: "course-a", color: "#abcdef", course_code: "CS 330" })];
    const attempts = [attempt({ quiz_id: "q1", concept_node_id: "n-low", score: 1, total: 4 })];
    const ranked = rankCandidates(nodes, courses, attempts, NOW);
    const low = ranked.find(c => c.node.id === "n-low");
    expect(low?.course?.course_code).toBe("CS 330");
    expect(low?.color).toBe("#abcdef");
    expect(low?.lastAttempt?.quiz_id).toBe("q1");
    expect(low?.rationale).toBe("12% · missed 3 last time");
  });
});

describe("primaryOf / alternativesOf", () => {
  const candidates = () =>
    rankCandidates(
      [
        node({ id: "never", mastery_score: 0, mastery_tier: "unexplored", times_studied: 0 }),
        node({ id: "studied", mastery_score: 0.29, times_studied: 3, last_studied_at: iso(2026, 8, 18) }),
        node({ id: "third", mastery_score: 0.4, mastery_tier: "learning", times_studied: 1 }),
        node({ id: "fourth", mastery_score: 0.5, mastery_tier: "learning", times_studied: 1 }),
      ],
      [],
      [],
      NOW,
    );

  it("prefers the weakest concept the student has actually opened (R-7)", () => {
    // The raw mastery_score.asc order puts `never` (0.0) first.
    expect(candidates()[0].node.id).toBe("never");
    expect(primaryOf(candidates())?.node.id).toBe("studied");
  });

  it("falls back to the literal first when nothing has been studied", () => {
    const fresh = rankCandidates(
      [node({ id: "a", mastery_score: 0, mastery_tier: "unexplored", times_studied: 0 })],
      [],
      [],
      NOW,
    );
    expect(primaryOf(fresh)?.node.id).toBe("a");
  });

  it("returns null when there is nothing to propose", () => {
    expect(primaryOf([])).toBeNull();
    expect(alternativesOf([], null)).toEqual([]);
  });

  it("gives two alternatives and never repeats the primary", () => {
    const c = candidates();
    const primary = primaryOf(c);
    const alts = alternativesOf(c, primary);
    expect(alts).toHaveLength(2);
    expect(alts.map(a => a.node.id)).not.toContain(primary?.node.id);
    expect(alts.map(a => a.node.id)).toEqual(["never", "third"]);
  });
});

describe("metaLine", () => {
  it("reads score, tier and when it was last studied", () => {
    expect(
      metaLine(
        node({ id: "n", mastery_score: 0.29, mastery_tier: "struggling", last_studied_at: iso(2026, 8, 18) }),
        NOW,
      ),
    ).toBe("29% · struggling · last studied 4 days ago");
  });

  it("says so when it has never been studied", () => {
    expect(
      metaLine(node({ id: "n", mastery_score: 0, mastery_tier: "unexplored", last_studied_at: null }), NOW),
    ).toBe("0% · unexplored · not studied yet");
  });
});

describe("rationaleFor", () => {
  it("names a never-studied concept", () => {
    expect(
      rationaleFor(node({ id: "n", mastery_score: 0.12, times_studied: 0, last_studied_at: null }), undefined, NOW),
    ).toBe("12% · not studied yet");
  });

  it("prefers the misses from the last completed attempt", () => {
    expect(
      rationaleFor(
        node({ id: "n", mastery_score: 0.44, last_studied_at: iso(2026, 8, 13) }),
        attempt({ quiz_id: "q", concept_node_id: "n", score: 2, total: 5 }),
        NOW,
      ),
    ).toBe("44% · missed 3 last time");
  });

  it("falls through to the days line for a clean sweep", () => {
    expect(
      rationaleFor(
        node({ id: "n", mastery_score: 0.31, last_studied_at: iso(2026, 8, 13) }),
        attempt({ quiz_id: "q", concept_node_id: "n", score: 5, total: 5 }),
        NOW,
      ),
    ).toBe("31% · not reviewed in 9 days");
  });

  it("reads naturally for today and yesterday", () => {
    expect(rationaleFor(node({ id: "n", mastery_score: 0.5, last_studied_at: iso(2026, 8, 22) }), undefined, NOW))
      .toBe("50% · reviewed today");
    expect(rationaleFor(node({ id: "n", mastery_score: 0.5, last_studied_at: iso(2026, 8, 21) }), undefined, NOW))
      .toBe("50% · reviewed yesterday");
  });

  it("does not claim 'not studied yet' for a studied node with no timestamp", () => {
    expect(rationaleFor(node({ id: "n", mastery_score: 0.2, times_studied: 4, last_studied_at: null }), undefined, NOW))
      .toBe("20% · not reviewed recently");
  });
});

describe("latestCompletedAttempt", () => {
  const attempts = [
    attempt({ quiz_id: "old", concept_node_id: "n", completed_at: "2026-08-01T00:00:00Z" }),
    attempt({ quiz_id: "new", concept_node_id: "n", completed_at: "2026-08-20T00:00:00Z" }),
    attempt({ quiz_id: "other", concept_node_id: "m", completed_at: "2026-08-21T00:00:00Z" }),
    attempt({ quiz_id: "open", concept_node_id: "n", status: "in_progress", score: null, total: null,
      completed_at: null, created_at: "2026-08-22T00:00:00Z" }),
  ];

  it("picks the newest completed attempt for that node only", () => {
    expect(latestCompletedAttempt("n", attempts)?.quiz_id).toBe("new");
  });

  it("ignores in-progress and abandoned rows — they carry no score", () => {
    expect(latestCompletedAttempt("z", attempts)).toBeUndefined();
    expect(latestCompletedAttempt("n", [attempts[3]])).toBeUndefined();
  });
});

describe("dueSet", () => {
  it("counts the whole scoped graph, not the capped recommendation list", () => {
    const nodes = Array.from({ length: 8 }, (_, i) =>
      node({ id: `n${i}`, mastery_score: i / 10, course_id: i < 5 ? "course-a" : "course-b" }));
    nodes.push(node({ id: "done", mastery_tier: "mastered", mastery_score: 0.95 }));

    const due = dueSet(nodes);
    expect(due.count).toBe(8);
    expect(due.courseCount).toBe(2);
    expect(due.conceptIds[0]).toBe("n0");
  });

  it("is empty for a graph with nothing to work on", () => {
    expect(dueSet([node({ id: "n", mastery_tier: "mastered" })]))
      .toEqual({ conceptIds: [], count: 0, courseCount: 0 });
  });

  it("does not count a null course id as a course", () => {
    expect(dueSet([node({ id: "n", course_id: null })]).courseCount).toBe(0);
  });
});

describe("queueFor", () => {
  const nodes = Array.from({ length: 8 }, (_, i) =>
    node({ id: `n${i}`, mastery_score: i / 10, course_id: i < 6 ? "course-a" : "course-b" }));

  it("caps a due queue at QUEUE_MAX, weakest first", () => {
    const queue = queueFor("due", nodes);
    expect(queue).toHaveLength(QUEUE_MAX);
    expect(queue).toEqual(["n0", "n1", "n2", "n3", "n4"]);
  });

  it("scopes a course queue to that course", () => {
    expect(queueFor("course", nodes, "course-b")).toEqual(["n6", "n7"]);
  });

  it("is empty for an unknown course", () => {
    expect(queueFor("course", nodes, "nope")).toEqual([]);
  });
});

describe("groupByCourse", () => {
  const nodes = [
    node({ id: "zebra", concept_name: "Zebra", course_id: "course-a" }),
    node({ id: "apple", concept_name: "Apple", course_id: "course-a" }),
    node({ id: "beta", concept_name: "Beta", course_id: "course-b" }),
    node({ id: "root", concept_name: "CS", course_id: "course-a", is_subject_root: true }),
    node({ id: "orphan", concept_name: "Orphan", course_id: null }),
  ];
  const courses = [
    course({ course_id: "course-b", course_code: "MA 225" }),
    course({ course_id: "course-a", course_code: "CS 330" }),
    course({ course_id: "course-empty", course_code: "AA 100" }),
  ];

  it("groups by course, courses by code and concepts by name", () => {
    const groups = groupByCourse(nodes, courses);
    expect(groups.map(g => g.course.course_code)).toEqual(["CS 330", "MA 225"]);
    expect(groups[0].nodes.map(n => n.concept_name)).toEqual(["Apple", "Zebra"]);
  });

  it("omits subject roots and courses with no concepts", () => {
    const groups = groupByCourse(nodes, courses);
    expect(groups.flatMap(g => g.nodes).map(n => n.id)).not.toContain("root");
    expect(groups.map(g => g.course.course_id)).not.toContain("course-empty");
  });
});

describe("colorFor", () => {
  it("prefers the node's own course colour, then the course record", () => {
    expect(colorFor(node({ id: "n", course_color: "#111111" }), course({ course_id: "course-a", color: "#222222" })))
      .toBe("#111111");
    expect(colorFor(node({ id: "n" }), course({ course_id: "course-a", color: "#222222" })))
      .toBe("#222222");
  });

  it("falls back to a deterministic palette entry", () => {
    const a = colorFor(node({ id: "n", course_id: "course-a" }), null);
    const b = colorFor(node({ id: "m", course_id: "course-a" }), null);
    expect(a).toMatch(/^#/);
    expect(a).toBe(b);
  });
});
