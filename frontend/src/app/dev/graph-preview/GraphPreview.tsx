"use client";

import React from "react";
import { KnowledgeGraph } from "@/components/graph/KnowledgeGraph";
import { CoursesKey, courseProgressFor } from "@/components/graph/CoursesKey";
import { paletteFor, type GraphEdge, type GraphNode } from "@/lib/data";

// "Name < A, B" = A and B are prerequisites of Name.
// "Name << A"   = Name builds on A.
// Lines are in rough syllabus order; later lines tend to be less mastered.
type CourseDef = { id: string; code: string; title: string; lines: string[]; related: [string, string][] };

const COURSES: CourseDef[] = [
  {
    id: "c-stat", code: "STAT 101", title: "Introductory Statistics",
    lines: [
      "Data Types", "Descriptive Statistics", "Measures of Center < Descriptive Statistics",
      "Measures of Spread < Measures of Center", "Histograms < Descriptive Statistics, Data Types",
      "Box Plots < Measures of Spread", "Probability", "Conditional Probability < Probability",
      "Bayes' Theorem < Conditional Probability", "Independence < Conditional Probability",
      "Random Variables < Probability", "Expected Value < Random Variables",
      "Variance < Expected Value, Measures of Spread", "Binomial Distribution < Random Variables, Independence",
      "Poisson Distribution << Binomial Distribution", "Normal Distribution < Random Variables, Histograms",
      "Z-Scores < Normal Distribution, Measures of Spread", "Sampling Distributions < Normal Distribution",
      "Central Limit Theorem < Sampling Distributions", "Standard Error < Sampling Distributions, Variance",
      "Confidence Intervals < Central Limit Theorem, Standard Error", "Hypothesis Testing < Sampling Distributions",
      "p-values << Hypothesis Testing", "Type I and II Errors < Hypothesis Testing",
      "t-tests < Hypothesis Testing, Standard Error", "Chi-Square Tests < Hypothesis Testing",
      "ANOVA << t-tests", "Correlation < Variance", "Linear Regression < Correlation",
      "Residual Analysis << Linear Regression",
    ],
    related: [["Confidence Intervals", "Hypothesis Testing"], ["p-values", "Type I and II Errors"], ["Box Plots", "Histograms"]],
  },
  {
    id: "c-cs", code: "CS 111", title: "Introduction to Computer Science",
    lines: [
      "Variables", "Data Types < Variables", "Expressions < Variables", "Conditionals < Expressions",
      "Loops < Conditionals", "Functions < Expressions", "Scope < Functions",
      "Recursion < Functions, Conditionals", "Lists < Loops, Data Types", "Strings < Data Types",
      "Dictionaries < Lists", "Tuples << Lists", "File I/O < Strings, Loops", "Exceptions < Functions",
      "Classes < Functions, Dictionaries", "Objects < Classes", "Inheritance < Classes",
      "Polymorphism << Inheritance", "Big-O Analysis < Loops", "Linear Search < Lists, Big-O Analysis",
      "Binary Search < Linear Search, Recursion", "Sorting < Lists, Big-O Analysis",
      "Merge Sort < Sorting, Recursion", "Quick Sort < Sorting, Recursion", "Stacks < Lists",
      "Queues < Lists", "Linked Lists < Objects", "Trees < Linked Lists, Recursion",
      "Binary Search Trees < Trees, Binary Search", "Hash Tables < Dictionaries, Big-O Analysis",
      "Graphs < Trees", "Breadth-First Search < Graphs, Queues",
    ],
    related: [["Stacks", "Queues"], ["Merge Sort", "Quick Sort"]],
  },
  {
    id: "c-la", code: "MA 242", title: "Linear Algebra",
    lines: [
      "Vectors", "Vector Operations < Vectors", "Dot Product < Vector Operations",
      "Linear Combinations < Vector Operations", "Span < Linear Combinations", "Linear Independence < Span",
      "Matrices < Vectors", "Matrix Multiplication < Matrices, Dot Product", "Systems of Equations < Matrices",
      "Gaussian Elimination < Systems of Equations", "Row Echelon Form << Gaussian Elimination",
      "Inverse Matrices < Matrix Multiplication, Row Echelon Form", "Determinants < Matrices",
      "Vector Spaces < Span", "Subspaces < Vector Spaces", "Basis < Linear Independence, Subspaces",
      "Dimension < Basis", "Rank < Row Echelon Form, Dimension", "Null Space < Subspaces, Gaussian Elimination",
      "Linear Transformations < Matrix Multiplication, Vector Spaces",
      "Eigenvalues < Determinants, Linear Transformations", "Eigenvectors < Eigenvalues, Null Space",
      "Diagonalization << Eigenvectors, Inverse Matrices", "Orthogonality < Dot Product, Basis",
    ],
    related: [["Rank", "Null Space"], ["Determinants", "Inverse Matrices"]],
  },
];

function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

function tierFor(score: number): GraphNode["mastery_tier"] {
  if (score <= 0) return "unexplored";
  if (score >= 0.75) return "mastered";
  if (score >= 0.4) return "learning";
  return "struggling";
}

/** The first `count` concepts of a course, keeping only links among them. */
function trim(c: CourseDef, count: number): CourseDef {
  if (count >= c.lines.length) return c;
  const nameOf = (line: string) => line.split(/<<?/)[0].trim();
  const kept = new Set(c.lines.slice(0, count).map(nameOf));
  const lines = c.lines.slice(0, count).map((line) => {
    const builds = line.includes("<<");
    const [name, rest] = line.split(builds ? "<<" : "<").map((s) => s.trim());
    const preds = (rest ?? "").split(",").map((s) => s.trim()).filter((p) => kept.has(p));
    return preds.length ? `${name} ${builds ? "<<" : "<"} ${preds.join(", ")}` : name;
  });
  return { ...c, lines, related: c.related.filter(([a, b]) => kept.has(a) && kept.has(b)) };
}

function build(courses: CourseDef[], withLinks: boolean) {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const rand = rng(42);
  for (const c of courses) {
    const color = paletteFor(c.id);
    const rootId = `subject_root__${c.id}`;
    nodes.push({
      id: rootId, name: `${c.code} - ${c.title}`, subject: c.title, color,
      is_subject_root: true, mastery_tier: "learning", mastery_score: 0.5, course_id: c.id,
    });
    const idOf = (name: string) => `${c.id}:${name}`;
    c.lines.forEach((line, i) => {
      const builds = line.includes("<<");
      const [name, rest] = line.split(builds ? "<<" : "<").map((s) => s.trim());
      // Syllabus position drives mastery: early topics mostly known, the last
      // third mostly untouched — with noise so it isn't a clean gradient.
      const f = i / c.lines.length;
      const score = f > 0.68 && rand() > 0.25 ? 0 : Math.max(0.05, Math.min(0.98, 0.95 - f * 0.9 + (rand() - 0.5) * 0.35));
      nodes.push({
        id: idOf(name), name, subject: c.title, color, mastery_score: score,
        mastery_tier: tierFor(score), course_id: c.id,
      });
      // The backend's synthesized spoke — the frontend now ignores these.
      edges.push({ source: rootId, target: idOf(name), strength: 0.7, relationship_type: "related" });
      if (!withLinks || !rest) return;
      for (const p of rest.split(",").map((s) => s.trim()).filter(Boolean)) {
        edges.push({
          source: idOf(p), target: idOf(name), strength: 0.6 + rand() * 0.3,
          relationship_type: builds ? "builds_on" : "prerequisite",
        });
      }
    });
    if (withLinks) {
      for (const [a, b] of c.related) {
        edges.push({ source: idOf(a), target: idOf(b), strength: 0.5, relationship_type: "related" });
      }
    }
  }
  return { nodes, edges };
}

function Toggle<T extends string | number | boolean>({
  label, value, options, onChange,
}: { label: string; value: T; options: { v: T; text: string }[]; onChange: (v: T) => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{label}</span>
      <div style={{ display: "flex", border: "1px solid var(--border, #ccc)", borderRadius: 8, overflow: "hidden" }}>
        {options.map((o) => (
          <button
            key={String(o.v)}
            type="button"
            onClick={() => onChange(o.v)}
            style={{
              padding: "5px 12px", fontSize: 13, border: 0, cursor: "pointer",
              background: o.v === value ? "var(--text, #222)" : "transparent",
              color: o.v === value ? "var(--bg, #fff)" : "var(--text, #222)",
            }}
          >
            {o.text}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function GraphPreview() {
  const [courseCount, setCourseCount] = React.useState<1 | 3>(3);
  // Most students' graphs are small; the layout has to read at 5 concepts too.
  const [perCourse, setPerCourse] = React.useState<5 | 12 | 99>(99);
  const [links, setLinks] = React.useState(true);
  const [legible, setLegible] = React.useState(true);
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const [size, setSize] = React.useState({ w: 1200, h: 800 });

  React.useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((e) => setSize({ w: e[0].contentRect.width, h: e[0].contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // The Dashboard's wiring: hover a row to fade the other courses, hover a
  // concept to light its row, click a row to zoom to the course, again to zoom out.
  const [keyHover, setKeyHover] = React.useState<string | null>(null);
  const [graphHover, setGraphHover] = React.useState<string | null>(null);
  const [zoomRequest, setZoomRequest] = React.useState<{ courseId: string | null; seq: number } | null>(null);
  const keyCourses = React.useMemo(
    () => COURSES.slice(0, courseCount).map((c) => ({
      course_id: c.id, course_code: c.code, course_name: c.title, color: paletteFor(c.id),
    })),
    [courseCount],
  );

  const data = React.useMemo(
    () => build(COURSES.slice(0, courseCount).map((c) => trim(c, perCourse)), links),
    [courseCount, perCourse, links],
  );
  const conceptCount = data.nodes.filter((n) => !n.is_subject_root).length;
  const linkCount = data.edges.filter((e) => !e.source.startsWith("subject_root__")).length;

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "var(--bg)", color: "var(--text)" }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 18, alignItems: "center", padding: "12px 16px", borderBottom: "1px solid var(--border, #ddd)" }}>
        <strong style={{ fontSize: 15 }}>Graph preview</strong>
        <Toggle label="Courses" value={courseCount} onChange={setCourseCount}
          options={[{ v: 1, text: "1" }, { v: 3, text: "3" }]} />
        <Toggle label="Concepts per course" value={perCourse} onChange={setPerCourse}
          options={[{ v: 5, text: "5" }, { v: 12, text: "12" }, { v: 99, text: "All" }]} />
        <Toggle label="Concept links" value={links} onChange={setLinks}
          options={[{ v: true, text: "On" }, { v: false, text: "Off (today's data)" }]} />
        <Toggle label="Obsidian legibility" value={legible} onChange={setLegible}
          options={[{ v: true, text: "On" }, { v: false, text: "Off" }]} />
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {conceptCount} concepts · {linkCount} concept links · hover a concept · scroll to zoom · dev only, made-up data
        </span>
      </div>
      <div ref={wrapRef} style={{ flex: 1, minHeight: 0, position: "relative" }}>
        {/* The same wrapper the Tree and Dashboard mount (Mastery colors
            toggle, crash boundary), not the bare 2D renderer. */}
        <KnowledgeGraph
          key={`${courseCount}-${perCourse}-${links}-${legible}`}
          nodes={data.nodes}
          edges={data.edges}
          width={size.w}
          height={size.h}
          legible={legible}
          focusCourseId={keyHover}
          onHoverCourse={setGraphHover}
          zoomRequest={zoomRequest}
        />
        {legible && courseCount > 1 && (
          <CoursesKey
            courseProgress={courseProgressFor(keyCourses, data.nodes)}
            placement="top-left"
            testIdPrefix="preview"
            activeCourseId={keyHover ?? graphHover}
            onHoverCourse={setKeyHover}
            selectedCourseId={zoomRequest?.courseId ?? null}
            onSelectCourse={(id) => setZoomRequest((r) => ({ courseId: r?.courseId === id ? null : id, seq: (r?.seq ?? 0) + 1 }))}
            selectHint="Click to zoom to this course, again to zoom out"
          />
        )}
      </div>
    </div>
  );
}
