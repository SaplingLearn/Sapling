// @vitest-environment jsdom
/**
 * Total coverage of the design handoff's style declarations.
 *
 * `designParity.test.tsx` checks specific values the rebuild must carry. This
 * file checks the complement: that NO declaration in the prototype was left
 * behind. Every `style="…"` declaration in the handoff must appear either in
 * the rendered DOM or somewhere in the rebuild's source — the latter because a
 * menu, modal, trash view or skeleton is not mounted in a single render.
 *
 * Two classes of declaration are deliberately NOT ported, and are listed in
 * `EXPECTED_DEVIATIONS` with the reason. Anything else failing here means a
 * declaration was dropped, so the port is no longer one-to-one.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { declarations, normalizeColor, renderedDeclarations } from "./designParity";

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/context/FlagsContext", () => ({
  useFlagMap: () => ({ flags: {}, ready: true }),
}));
vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(), getCourses: vi.fn(),
  getFolders: vi.fn(async () => ({ folders: [] })),
  getTrashedDocuments: vi.fn(async () => ({ documents: [] })),
  deleteDocument: vi.fn(), restoreDocument: vi.fn(), purgeDocument: vi.fn(),
  updateDocument: vi.fn(), createFolder: vi.fn(),
  renameFolder: vi.fn(), deleteFolder: vi.fn(), scanDocumentConcepts: vi.fn(),
  scanCourseConcepts: vi.fn(), uploadDocumentStream: vi.fn(),
}));
vi.mock("@/lib/studyGuide/api", () => ({ listGuides: vi.fn(async () => ({ guides: [] })) }));

import { getCourses, getDocuments, type EnrolledCourse } from "@/lib/api";
import { Library } from "./Library";
import { ToastProvider } from "../ToastProvider";

const read = (p: string) => fs.readFileSync(path.join(__dirname, p), "utf8");
const LIBRARY_DESIGN = read("__fixtures__/library-v2.design.html");

/**
 * Declarations the rebuild deliberately does not carry.
 *
 * The fonts: `next/font/local` registers a GENERATED family name, so a bare
 * `'Aleo'` / `'SUSE'` / `'IBM Plex Mono'` silently falls back to Times. The
 * rebuild uses `var(--font-serif|sans|mono)`, which resolve to those faces.
 *
 * The artboard: the prototype letterboxes itself into a fixed 1920x1080 canvas
 * (`position: absolute; transform: {{ fitT }}; transform-origin: 0 0`) so it
 * can be previewed at any window size. The real page is responsive inside the
 * repo's own shell, so that wrapper has no counterpart.
 *
 * The scroller: the prototype pins the title, search and scope bar and scrolls
 * the document list alone (`grid-template-rows: auto minmax(0, 1fr)` with
 * `overflow-y: auto` on the list). Owner's call 2026-11-24 — the whole page
 * scrolls instead, so the header travels up with the documents, which means
 * the rows track `auto auto` and the page owns the overflow. The two
 * `min-height: 0`s the prototype needs for that inner scroller (the documents
 * section and the list inside it) go with it; they are its only two.
 *
 * The control height: the handoff draws the search field and Upload at 48px.
 * Owner's call 2026-11-25 — too heavy for the row — so both come down to the
 * Study hub tool button's 40px (`primitives.ts::CONTROL_H`), and the
 * skeleton's matching bars with them. ONLY the height moves: the paddings,
 * radii and type sizes are still the handoff's, so this one regex is the whole
 * deviation. Exactly the four header elements in the prototype carry
 * `height: 48px`, so allowlisting it hides nothing else. The upload menu's
 * `top: 54px` goes with it: the prototype's 54 is its 48px button plus 6, so
 * the faithful offset at 40px is 46 — the rebuild writes `CONTROL_H + 6` so
 * the menu keeps following the button. It is the only `top: 54px` there.
 *
 * The Trash count: the handoff puts a tabular count after the word, and
 * baseline-aligns the label to it. Owner's call 2026-11-25 removed the count,
 * so the label is the chip's only content and centres on the icon instead —
 * which leaves `align-items: baseline` with nothing left to align. It is the
 * only baseline in the prototype. The count's own `display: inline-block`
 * (its bump animation needs a box) goes with the count; it is the only one.
 */
const EXPECTED_DEVIATIONS = [
  /^font-family: '(Aleo|SUSE|IBM Plex Mono)'/,
  /^width: 1920px$/, /^height: 1080px$/, /^transform-origin: 0 0$/,
  /^grid-template-rows: auto minmax\(0, 1fr\)$/, /^min-height: 0$/,
  /^height: 48px$/, /^top: 54px$/,
  /^align-items: baseline$/, /^display: inline-block$/,
];

/** The rebuild's own source: components, hooks, and the ported stylesheet. */
function sourceText(): string {
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== "__fixtures__") walk(full); continue; }
      if (/\.(tsx?|css)$/.test(e.name) && !e.name.includes(".test.")) files.push(full);
    }
  };
  walk(path.join(__dirname, "..", "library"));
  files.push(path.join(__dirname, "../../app/library-notes.css"));
  return files.map(f => fs.readFileSync(f, "utf8")).join("\n");
}

// `SQUEEZE` is the design's 380ms easing, named once so the toolbar's eleven
// transitions cannot drift apart; expand it back out before comparing.
const SOURCE = sourceText()
  .replace(/\s+/g, " ")
  .replace(/\$\{SQUEEZE\}/g, "380ms cubic-bezier(0.3, 0.7, 0.2, 1)")
  .replace(/` \+ `/g, "");

const isColor = (v: string) => /^(#[0-9A-Fa-f]{3,8}|rgba?\([^)]*\))$/.test(v.trim());
const norm = (p: string, v: string) => `${p}: ${isColor(v) ? normalizeColor(v) : v}`;

/** A transition/animation list means the same thing in any order. */
const asSet = (v: string) => v.split(",").map(s => s.trim()).sort().join(" | ");

function carried(have: Set<string>, haveSets: Set<string>, p: string, v: string): boolean {
  if (have.has(norm(p, v))) return true;
  if (/^(transition|animation)$/.test(p) && haveSets.has(asSet(v))) return true;
  const camel = p.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
  const bare = v.replace(/px$/, "");
  for (const needle of [
    `${p}: ${v}`, `${p}:${v}`,
    `${camel}: "${v}"`, `${camel}: '${v}'`, `${camel}: \`${v}\``,
    `${camel}: ${bare},`, `${camel}: ${bare} `, `${camel}: ${bare}}`,
    `${p}="${v}"`, `${camel}="${v}"`,
    `${p}={${bare}}`, `${camel}={${bare}}`, `${p}={"${v}"}`, `${camel}={"${v}"}`,
    // A primitive's default (`MenuScrim({ zIndex = 30 })`), and a square one
    // sized by one prop (`<CheckBox size={22} />` sets width and height).
    `${camel} = ${bare},`, `${camel} = ${bare} `, `${camel} = ${bare}}`,
    ...(/^(width|height)$/.test(p) ? [`size={${bare}}`] : []),
  ]) if (SOURCE.includes(needle)) return true;
  // A value chosen by a ternary (`border: final ? "…" : "1px solid #445D22"`)
  // is never preceded by its property name. Multi-token values are specific
  // enough to look for on their own; single tokens like `0` are not.
  if (/\s/.test(v) && (SOURCE.includes(`"${v}"`) || SOURCE.includes(`'${v}'`))) return true;
  return false;
}

function dropped(design: string, root: HTMLElement): string[] {
  const have = new Set<string>();
  const haveSets = new Set<string>();
  for (const [p, v] of renderedDeclarations(root)) {
    have.add(norm(p, v));
    if (/^(transition|animation)$/.test(p)) haveSets.add(asSet(v));
  }
  for (const m of SOURCE.matchAll(/(transition|animation): [`"']([^`"']*)[`"']/g)) {
    haveSets.add(asSet(m[2]));
  }
  const seen = new Set<string>();
  const out: string[] = [];
  for (const [p, v] of declarations(design)) {
    if (v.includes("{{")) continue;
    const key = norm(p, v);
    if (seen.has(key)) continue;
    seen.add(key);
    if (EXPECTED_DEVIATIONS.some(re => re.test(key))) continue;
    if (!carried(have, haveSets, p, v)) out.push(key);
  }
  return out.sort();
}

const COURSE = {
  enrollment_id: "e1", course_id: "c1", course_code: "MATH210",
  course_name: "Linear Algebra", color: "#C06020",
} as EnrolledCourse;
const DOC = {
  id: "d1", user_id: "u1", course_id: "c1", file_name: "Determinants Lecture 7.pdf",
  category: "lecture_notes" as const, summary: "Cofactor expansion.",
  concept_notes: [{ name: "Determinants", description: "" }], page_count: 18,
  created_at: "2026-11-05T00:00:00Z", processed_at: "2026-11-05T00:00:00Z",
};

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(getDocuments).mockResolvedValue({ documents: [DOC] } as never);
  vi.mocked(getCourses).mockResolvedValue({ courses: [COURSE] });
});

describe("every design declaration was ported", () => {
  it("the Library drops nothing", async () => {
    const view = render(<ToastProvider><Library /></ToastProvider>);
    await screen.findByTestId("library-doc-d1");
    expect(dropped(LIBRARY_DESIGN, view.container as HTMLElement)).toEqual([]);
  });
});
