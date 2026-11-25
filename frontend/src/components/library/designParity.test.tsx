// @vitest-environment jsdom
/**
 * The Library against the design handoff, read from the handoff itself.
 *
 * `__fixtures__/library-v2.design.html` is the prototype the rebuild was made
 * from, kept here verbatim. Each test pulls a literal out of it and asserts
 * the rebuilt page carries the same value — so a later edit that
 * drifts from the design fails rather than passing quietly.
 *
 * What it does NOT claim: that the page is pixel-identical. jsdom has no
 * layout engine. It checks what can be checked without one — the exact
 * colours, sizes, radii, copy, icon geometry and animations.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import {
  colors, declares, keyframeNames, keyframesUsed, paths, renderedAnimations,
  renderedColors, renderedPaths, renderedValuesFor, valuesFor,
} from "./designParity";

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/context/FlagsContext", () => ({
  useFlagMap: () => ({ flags: {}, ready: true }),
}));
vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  getCourses: vi.fn(),
  deleteDocument: vi.fn(),
  scanDocumentConcepts: vi.fn(),
  scanCourseConcepts: vi.fn(),
  uploadDocumentStream: vi.fn(),
}));
vi.mock("@/lib/libraryApi", () => ({
  getFolders: vi.fn(async () => ({ folders: [] })),
  getTrashedDocuments: vi.fn(async () => ({ documents: [] })),
  restoreDocument: vi.fn(),
  purgeDocument: vi.fn(),
  updateDocument: vi.fn(),
  createFolder: vi.fn(),
  renameFolder: vi.fn(),
  deleteFolder: vi.fn(),
}));
vi.mock("@/lib/studyGuide/api", () => ({ listGuides: vi.fn(async () => ({ guides: [] })) }));

import { getCourses, getDocuments, type EnrolledCourse } from "@/lib/api";
import { Library } from "./Library";
import { ToastProvider } from "../ToastProvider";
import { GLYPHS } from "./glyphs";
import { CONTROL_H } from "./primitives";

const read = (p: string) => fs.readFileSync(path.join(__dirname, p), "utf8");
const LIBRARY_DESIGN = read("__fixtures__/library-v2.design.html");
const LIBRARY_CSS = fs.readFileSync(
  path.join(__dirname, "../../app/library-notes.css"), "utf8",
);

const COURSE = {
  enrollment_id: "e1", course_id: "c1", course_code: "MATH210",
  course_name: "Linear Algebra", color: "#C06020",
} as EnrolledCourse;

const DOC = {
  id: "d1", user_id: "u1", course_id: "c1", file_name: "Determinants Lecture 7.pdf",
  category: "lecture_notes" as const,
  summary: "Cofactor expansion, row operations, and why a zero determinant means no inverse.",
  concept_notes: [{ name: "Determinants", description: "" }],
  page_count: 18,
  created_at: "2026-11-05T00:00:00Z", processed_at: "2026-11-05T00:00:00Z",
};

async function renderLibrary() {
  const view = render(<ToastProvider><Library /></ToastProvider>);
  await screen.findByTestId("library-doc-d1");
  return view.container as HTMLElement;
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(getDocuments).mockResolvedValue({ documents: [DOC] } as never);
  vi.mocked(getCourses).mockResolvedValue({ courses: [COURSE] });
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

// ── the palette ─────────────────────────────────────────────────────────────

describe("colours come from the design, not from somewhere else", () => {
  /**
   * Colours the rebuild is allowed to use that the prototype has no literal
   * for, each with the reason. Anything else in the rendered DOM must appear
   * in the design file.
   */
  const ALLOWED = new Set([
    // The repo's own token values, which the design restates as literals.
    "#FAF8F3", "#FDFCF9",
    // A real course's colour comes from the student's data; the prototype's
    // mock courses have their own.
    "#C06020",
  ]);

  it("the Library uses only the design's colours", async () => {
    const root = await renderLibrary();
    const allowed = new Set([...colors(LIBRARY_DESIGN), ...ALLOWED]);
    const used = [...renderedColors(root)].filter(c => !allowed.has(c));
    expect(used).toEqual([]);
  });

});

// ── sizes the design states exactly ─────────────────────────────────────────

describe("the design's measurements are the rebuild's", () => {
  it("every border radius the Library renders is one the design names", async () => {
    const root = await renderLibrary();
    const allowed = valuesFor(LIBRARY_DESIGN, "border-radius");
    const used = [...renderedValuesFor(root, "border-radius")]
      // React serialises a numeric radius as `12px`, the design writes `12px`.
      .filter(v => !allowed.has(v));
    expect(used).toEqual([]);
  });

  /**
   * Two owner's calls on 2026-11-25 land on this button, so the height and
   * radius asserted here are decisions rather than the drawing: it scaled down
   * with the other header controls (`primitives.ts::CONTROL_H`), and it took
   * the Study Guide button's 6px edge so the pair matches. Both values are
   * still ones the design names elsewhere, and the fill and weight are
   * untouched.
   */
  it("the upload split button keeps the design's fill and weight", async () => {
    await renderLibrary();
    const upload = screen.getByTestId("library-upload");
    expect(upload.style.height).toBe(`${CONTROL_H}px`);
    expect(upload.style.borderRadius).toBe("6px");
    expect(upload.style.background).toBe("rgb(68, 93, 34)"); // #445D22
    expect(upload.style.fontWeight).toBe("700");
  });

  it("a row's file tile is the design's 30×38 at radius 5", async () => {
    await renderLibrary();
    const row = screen.getByTestId("library-doc-d1");
    const tile = row.querySelector("[title]") as HTMLElement;
    expect(tile.style.width).toBe("30px");
    expect(tile.style.height).toBe("38px");
    expect(tile.style.borderRadius).toBe("5px");
  });

});

// ── copy ────────────────────────────────────────────────────────────────────

describe("the copy is the design's, verbatim", () => {
  /** Text the page shows straight away. */
  const ALWAYS_VISIBLE = [
    "Library", "Upload", "All Documents", "Trash", "List", "Panel",
    "Name", "Course", "Pages", "Added",
  ];

  it.each(ALWAYS_VISIBLE)("the design says %j, and so does the Library", async text => {
    expect(declares(LIBRARY_DESIGN, text)).toBe(true);
    const root = await renderLibrary();
    expect(root.textContent).toContain(text);
  });

  /** Text behind the Upload split button's menu. */
  const IN_NEW_MENU = ["Upload Documents", "New Folder"];

  it.each(IN_NEW_MENU)("the New menu says %j, as the design does", async text => {
    expect(declares(LIBRARY_DESIGN, text)).toBe(true);
    await renderLibrary();
    fireEvent.click(screen.getByTestId("library-upload"));
    expect(await screen.findByRole("menuitem", { name: text })).toBeTruthy();
  });

  it("the Type menu's options read as the design writes them", async () => {
    await renderLibrary();
    fireEvent.click(screen.getByRole("button", { name: /^Type/ }));
    for (const label of ["All Types", "Lecture Notes", "Slides", "Study Guide"]) {
      expect(declares(LIBRARY_DESIGN, label), `design copy: ${label}`).toBe(true);
      expect(screen.getByRole("menuitemradio", { name: new RegExp(label) })).toBeTruthy();
    }
  });

  it("the Sort menu's options read as the design writes them", async () => {
    await renderLibrary();
    fireEvent.click(screen.getByRole("button", { name: /^Sort/ }));
    for (const label of [
      "Recently Added", "Oldest First", "Name A–Z", "Course", "Type", "Most Pages",
    ]) {
      expect(declares(LIBRARY_DESIGN, label), `design copy: ${label}`).toBe(true);
      expect(screen.getByRole("menuitemradio", { name: label })).toBeTruthy();
    }
  });

  it("the search placeholder is the design's sentence", async () => {
    const placeholder = "Search titles, summaries, and concepts";
    expect(LIBRARY_DESIGN).toContain(`placeholder="${placeholder}"`);
    await renderLibrary();
    expect(screen.getByTestId("library-search").getAttribute("placeholder"))
      .toBe(placeholder);
  });

  it("the headings are Title Case, as the handoff requires", async () => {
    const root = await renderLibrary();
    expect(root.textContent).toContain("All Documents");
    expect(screen.getByTestId("library-view-panel").textContent).toBe("Panel");
  });
});

// ── icons ───────────────────────────────────────────────────────────────────

describe("the icons are the design's own path data", () => {
  it("every brand glyph is the design's, path for path", () => {
    // `const I = {…}` / `const TUTOR = {…}` are JSON inside the design's
    // script block, so the path data is matched against the file text rather
    // than against an element.
    for (const [name, glyph] of Object.entries(GLYPHS)) {
      for (const d of glyph.d) {
        expect(LIBRARY_DESIGN.includes(d), `${name}: path not in the design`).toBe(true);
      }
      expect(LIBRARY_DESIGN.includes(`"vb":"${glyph.vb}"`), `${name}: viewBox`).toBe(true);
    }
  });

  it("the single-path strokes the Library renders are the design's", async () => {
    const root = await renderLibrary();
    const designPaths = new Set([
      ...paths(LIBRARY_DESIGN),
      ...Object.values(GLYPHS).flatMap(g => g.d.map(d => d.replace(/\s+/g, " ").trim())),
    ]);
    const unknown = [...renderedPaths(root)].filter(d => !designPaths.has(d));
    expect(unknown).toEqual([]);
  });

  it("the folder is the design's #B8873F wherever it is drawn", async () => {
    expect(colors(LIBRARY_DESIGN).has("#B8873F")).toBe(true);
    await renderLibrary();
    fireEvent.click(screen.getByTestId("library-upload"));
    const item = await screen.findByRole("menuitem", { name: "New Folder" });
    const svg = item.querySelector("svg")!;
    expect(svg.getAttribute("fill")).toBe("#B8873F");
    expect(svg.getAttribute("stroke")).toBe("#B8873F");
  });
});

// ── motion ──────────────────────────────────────────────────────────────────

describe("the animations are the design's", () => {
  /** Every keyframe the design file declares. */
  const DESIGN_KEYFRAMES = keyframeNames(LIBRARY_DESIGN);

  it("the stylesheet carries every keyframe the design declares", () => {
    const ported = keyframeNames(LIBRARY_CSS);
    for (const name of DESIGN_KEYFRAMES) {
      expect(ported.has(name), `${name} is missing from library-notes.css`).toBe(true);
    }
  });

  it("the named ones the handoff calls out are all there", () => {
    for (const name of [
      "sapFadeIn", "sapSlideUp", "sapMenuIn", "sapMenuOut",
      "sapShimmer", "sapSkelOut", "sapRowOut", "sapBumpA", "sapBumpB",
      "sapLidA", "sapLidB", "sapScrimIn", "sapScrimOut", "sapModalIn", "sapModalOut",
    ]) {
      expect(keyframeNames(LIBRARY_CSS).has(name), name).toBe(true);
    }
  });

  it("every animation the Library plays names a keyframe that exists", async () => {
    const root = await renderLibrary();
    const used = keyframesUsed(renderedAnimations(root));
    expect(used.size).toBeGreaterThan(0);
    for (const name of used) {
      expect(keyframeNames(LIBRARY_CSS).has(name), name).toBe(true);
    }
  });

  it("rows stagger 30ms apart, as the handoff specifies", async () => {
    await renderLibrary();
    const row = screen.getByTestId("library-doc-d1");
    // The first row: 0 × 30 + 40.
    expect(row.style.animationDelay).toBe("40ms");
    expect(row.style.animation).toContain("sapSlideUp 420ms");
  });

  it("the skeleton fades out at 720ms, under content that enters later", async () => {
    render(<ToastProvider><Library /></ToastProvider>);
    const skeleton = await screen.findByTestId("library-skeleton");
    expect(skeleton.style.animation).toBe("sapSkelOut 260ms ease 720ms both");
  });

  it("reduced motion is honoured, scoped to the page", () => {
    expect(LIBRARY_CSS).toContain("prefers-reduced-motion: reduce");
    expect(LIBRARY_CSS).toContain("[data-sap-surface]");
  });
});

// ── fonts ───────────────────────────────────────────────────────────────────

describe("the three faces are used where the design uses them", () => {
  it("never falls back to a system font", async () => {
    const root = await renderLibrary();
    for (const family of renderedValuesFor(root, "font-family")) {
      expect(
        /--font-(serif|sans|mono)/.test(family) || family === "inherit",
        `unexpected font stack: ${family}`,
      ).toBe(true);
    }
  });

  it("the stylesheet never names a face by its literal family", () => {
    // next/font registers each face under a generated name, so a bare 'Aleo'
    // would silently render Times. The Library's faces are all set inline,
    // through var(--font-serif|sans|mono) (the test above).
    expect(LIBRARY_CSS).not.toMatch(/font-family:[^;]*'Aleo'/);
    expect(LIBRARY_CSS).not.toMatch(/font-family:[^;]*'SUSE'/);
    expect(LIBRARY_CSS).not.toMatch(/font-family:[^;]*'IBM Plex Mono'/);
  });

  it("the Library title is Aleo at the design's 34px", async () => {
    await renderLibrary();
    const h1 = screen.getByRole("heading", { name: "Library", level: 1 });
    expect(h1.style.fontSize).toBe("34px");
    expect(h1.style.fontWeight).toBe("600");
    expect(h1.style.fontFamily).toContain("--font-serif");
  });
});
