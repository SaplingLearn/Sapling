// @vitest-environment jsdom
/**
 * Library and Notes against the design handoff, read from the handoff itself.
 *
 * `__fixtures__/library-v2.design.html` and
 * `../notes/__fixtures__/notes.design.html` are the prototypes the rebuild was
 * made from, kept here verbatim. Each test pulls a literal out of one of them
 * and asserts the rebuilt page carries the same value — so a later edit that
 * drifts from the design fails rather than passing quietly.
 *
 * What it does NOT claim: that the pages are pixel-identical. jsdom has no
 * layout engine. It checks what can be checked without one — the exact
 * colours, sizes, radii, copy, icon geometry and animations.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

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
vi.mock("@/lib/notes/useNoteMath", () => ({
  useNoteMath: () => ({
    open: vi.fn(), close: vi.fn(), active: null, paletteOpen: false,
    insert: vi.fn(), preview: () => "", refresh: vi.fn(),
    palettePos: { left: 0, top: 0 },
  }),
}));
vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  getCourses: vi.fn(),
  deleteDocument: vi.fn(),
  scanDocumentConcepts: vi.fn(),
  scanCourseConcepts: vi.fn(),
  uploadDocumentStream: vi.fn(),
  getDocumentNotes: vi.fn(),
  saveDocumentNotes: vi.fn(),
  regenerateDocumentNotes: vi.fn(),
  askDocumentNotes: vi.fn(),
}));
vi.mock("@/lib/libraryApi", () => ({
  getFolders: vi.fn(async () => ({ folders: [] })),
  getTrashedDocuments: vi.fn(async () => ({ documents: [] })),
  restoreDocument: vi.fn(),
  purgeDocument: vi.fn(),
  updateDocument: vi.fn(),
  createBlankDocument: vi.fn(),
  createFolder: vi.fn(),
  renameFolder: vi.fn(),
  deleteFolder: vi.fn(),
}));
vi.mock("@/lib/studyGuide/api", () => ({ listGuides: vi.fn(async () => ({ guides: [] })) }));

import { getCourses, getDocumentNotes, getDocuments, type EnrolledCourse } from "@/lib/api";
import { Library } from "./Library";
import { Notes } from "../notes/Notes";
import { ToastProvider } from "../ToastProvider";
import { GLYPHS } from "./glyphs";
import { CONTROL_H } from "./primitives";

const read = (p: string) => fs.readFileSync(path.join(__dirname, p), "utf8");
const LIBRARY_DESIGN = read("__fixtures__/library-v2.design.html");
const NOTES_DESIGN = read("../notes/__fixtures__/notes.design.html");
const LIBRARY_CSS = fs.readFileSync(
  path.join(__dirname, "../../app/library-notes.css"), "utf8",
);
const NOTES_CSS = fs.readFileSync(
  path.join(__dirname, "../../app/notes-editor.css"), "utf8",
);
/** Both ported stylesheets: globals.css imports the two, so a keyframe or a
 *  hover class either page uses may live in either file. */
const PORTED_CSS = `${LIBRARY_CSS}\n${NOTES_CSS}`;

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

const NOTES_ROW = {
  document_id: "d1", user_id: "u1", title: "Determinants",
  content: "<h2>Overview</h2><p>What a determinant measures.</p>",
  final: false,
  created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z",
};

async function renderLibrary() {
  const view = render(<ToastProvider><Library /></ToastProvider>);
  await screen.findByTestId("library-doc-d1");
  return view.container as HTMLElement;
}

async function renderNotes() {
  const view = render(<ToastProvider><Notes documentId="d1" /></ToastProvider>);
  await screen.findByTestId("notes-editor");
  await waitFor(() => expect(screen.getByTestId("notes-title").textContent).toBe("Determinants"));
  return view.container as HTMLElement;
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(getDocuments).mockResolvedValue({ documents: [DOC] } as never);
  vi.mocked(getCourses).mockResolvedValue({ courses: [COURSE] });
  vi.mocked(getDocumentNotes).mockResolvedValue(NOTES_ROW);
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

  it("the Notes page uses only the design's colours", async () => {
    const root = await renderNotes();
    const allowed = new Set([
      ...colors(NOTES_DESIGN),
      ...colors(LIBRARY_DESIGN), // the shared primitives (Glyph, menus)
      ...ALLOWED,
    ]);
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

  it("the Notes title is Aleo at 40px, as drawn", async () => {
    await renderNotes();
    const title = screen.getByTestId("notes-title");
    expect(title.style.fontSize).toBe("40px");
    expect(title.style.fontWeight).toBe("600");
    expect(title.style.letterSpacing).toBe("-0.02em");
    expect(title.style.fontFamily).toContain("--font-serif");
  });

  it("the Ask Clov panel is the design's 440px", async () => {
    await renderNotes();
    const panel = screen.getByTestId("notes-clov");
    expect(panel.style.width).toBe("440px");
  });
});

// ── copy ────────────────────────────────────────────────────────────────────

describe("the copy is the design's, verbatim", () => {
  /** Text the page shows straight away. */
  const ALWAYS_VISIBLE = [
    "Library", "Upload", "All Documents", "List", "Panel",
    "Name", "Course", "Pages", "Added",
  ];

  it.each(ALWAYS_VISIBLE)("the design says %j, and so does the Library", async text => {
    expect(declares(LIBRARY_DESIGN, text)).toBe(true);
    const root = await renderLibrary();
    expect(root.textContent).toContain(text);
  });

  /** Text behind the Upload split button's menu. */
  const IN_NEW_MENU = ["Upload Documents", "New Document", "New Folder"];

  it.each(IN_NEW_MENU)("the New menu says %j, as the design does", async text => {
    expect(declares(LIBRARY_DESIGN, text)).toBe(true);
    await renderLibrary();
    fireEvent.click(screen.getByTestId("library-upload"));
    expect(await screen.findByRole("menuitem", { name: text })).toBeTruthy();
  });

  // The design's "Trash" sat on a chip beside the course switcher. Owner's
  // call 2026-11-25 moved it into the switcher as its last option, so the word
  // is still the design's but is one click in, not on the page at rest.
  it("the design says \"Trash\", and the course switcher offers it, last", async () => {
    expect(declares(LIBRARY_DESIGN, "Trash")).toBe(true);
    await renderLibrary();
    expect(screen.queryByTestId("library-trash")).toBeNull();
    fireEvent.click(screen.getByTestId("library-course-switcher"));
    const options = screen.getAllByRole("option");
    expect(options[options.length - 1].textContent).toContain("Trash");
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

  it("the Notes header reads as the design writes it", async () => {
    // Share and Download keep their labels only when Clov leaves room; the
    // design does the same, so the test opens the page with Clov closed.
    localStorage.setItem("sapling:clovClosed", "1");
    const root = await renderNotes();
    for (const text of ["Ask Clov", "Share", "Download", "Finalize", "Insert"]) {
      expect(declares(NOTES_DESIGN, text), `design copy: ${text}`).toBe(true);
      expect(root.textContent).toContain(text);
    }
  });

  it("the Insert menu lists the design's blocks, with its descriptions", async () => {
    localStorage.setItem("sapling:clovClosed", "1");
    await renderNotes();
    fireEvent.mouseDown(screen.getByTestId("notes-insert"));
    for (const label of [
      "Math Equation", "Matrix Calculator", "Table", "Checklist",
      "Toggle Section", "Practice Question", "Flashcard", "Code Block", "Divider",
    ]) {
      expect(await screen.findByRole("menuitem", { name: new RegExp(label) })).toBeTruthy();
    }
    // The five graph kinds sit above them, as the design draws it.
    for (const label of ["Function", "Bar", "Line", "Scatter", "Pie"]) {
      expect(screen.getByRole("menuitem", { name: label })).toBeTruthy();
    }
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
    // than against an element. Clov's mark comes from the Notes design.
    for (const [name, glyph] of Object.entries(GLYPHS)) {
      const source = name === "clov" ? NOTES_DESIGN : LIBRARY_DESIGN;
      for (const d of glyph.d) {
        expect(source.includes(d), `${name}: path not in the design`).toBe(true);
      }
      expect(source.includes(`"vb":"${glyph.vb}"`), `${name}: viewBox`).toBe(true);
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

  /**
   * The one icon the prototype has no drawing for.
   *
   * Its script carries a `regenerate()` but renders no button for it, while
   * the handoff (README §4) requires a "Regenerate Notes" button that asks
   * before replacing the student's edits. The button is therefore new, and so
   * is its circular-arrow glyph — drawn on the same 16×16 grid and 1.6 stroke
   * as the Share and Download icons beside it.
   */
  const REGENERATE_ICON = [
    "M13.5 8a5.5 5.5 0 1 1-1.6-3.9",
    "M13.5 2.5V5H11",
  ];

  it("the single-path strokes the Notes page renders are the design's", async () => {
    localStorage.setItem("sapling:clovClosed", "1");
    const root = await renderNotes();
    // The toolbar's icons live in the design's `const P = {…}` table rather
    // than in its markup, so the whole file is the reference.
    const unknown = [...renderedPaths(root)].filter(d =>
      !NOTES_DESIGN.includes(d)
      && !LIBRARY_DESIGN.includes(d)
      && !REGENERATE_ICON.includes(d));
    expect(unknown).toEqual([]);
  });

  it("the toolbar's own icons come from the design's path table", () => {
    for (const d of [
      "M6 4L3 7l3 3M3 7h7.5a4 4 0 0 1 0 8H8",           // undo
      "M12 4l3 3-3 3M15 7H7.5a4 4 0 0 0 0 8H10",        // redo
      "M7 5h8M7 9h8M7 13h8M3.5 5h.01M3.5 9h.01M3.5 13h.01",  // bulleted list
      "M10.5 3.5l4 4-6.5 6.5H4v-4zM3 16h12",            // highlight
      "M6.5 5L2.5 9l4 4M11.5 5l4 4-4 4",                // inline code
      "M3 4.5h12M3 8h8M3 11.5h12M3 15h8",               // align left
    ]) {
      expect(NOTES_DESIGN.includes(d), d.slice(0, 24)).toBe(true);
    }
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
  /** Every keyframe the two design files declare. */
  const DESIGN_KEYFRAMES = new Set([
    ...keyframeNames(LIBRARY_DESIGN),
    ...keyframeNames(NOTES_DESIGN),
  ]);

  /**
   * The Trash chip's can: the landing bump and the lid tilt. The chip is gone
   * (owner's call 2026-11-25; the Trash is the switcher's last option, not a
   * drop target), and these four animated nothing else. Pinned both ways, so
   * the exception cannot quietly grow or go stale.
   */
  const REMOVED_WITH_TRASH_CHIP = ["sapBumpA", "sapBumpB", "sapLidA", "sapLidB"];

  it("the stylesheet carries every keyframe the design declares", () => {
    const ported = keyframeNames(PORTED_CSS);
    for (const name of DESIGN_KEYFRAMES) {
      if (REMOVED_WITH_TRASH_CHIP.includes(name)) continue;
      expect(ported.has(name), `${name} is missing from the ported stylesheets`).toBe(true);
    }
  });

  it("only the Trash chip's keyframes are left out, and they really are out", () => {
    const ported = keyframeNames(LIBRARY_CSS);
    for (const name of REMOVED_WITH_TRASH_CHIP) {
      expect(DESIGN_KEYFRAMES.has(name), `${name} is the design's`).toBe(true);
      expect(ported.has(name), `${name} should be gone`).toBe(false);
    }
  });

  it("the named ones the handoff calls out are all there", () => {
    for (const name of [
      "sapFadeIn", "sapSlideUp", "sapMenuIn", "sapMenuOut",
      "sapShimmer", "sapSkelOut", "sapRowOut",
      "sapScrimIn", "sapScrimOut", "sapModalIn", "sapModalOut",
      "sapDot", "sapCaret",
    ]) {
      expect(keyframeNames(PORTED_CSS).has(name), name).toBe(true);
    }
  });

  it("every animation the Library plays names a keyframe that exists", async () => {
    const root = await renderLibrary();
    const used = keyframesUsed(renderedAnimations(root));
    expect(used.size).toBeGreaterThan(0);
    for (const name of used) {
      expect(keyframeNames(PORTED_CSS).has(name), name).toBe(true);
    }
  });

  it("every animation the Notes page plays names a keyframe that exists", async () => {
    const root = await renderNotes();
    const used = keyframesUsed(renderedAnimations(root));
    expect(used.size).toBeGreaterThan(0);
    for (const name of used) {
      expect(keyframeNames(PORTED_CSS).has(name), name).toBe(true);
    }
  });

  it("rows stagger 30ms apart, as the handoff specifies", async () => {
    await renderLibrary();
    const row = screen.getByTestId("library-doc-d1");
    // The first row: 0 × 30 + 40.
    expect(row.style.animationDelay).toBe("40ms");
    expect(row.style.animation).toContain("sapSlideUp 420ms");
  });

  it("the toolbar and the Clov panel share the 380ms curve", async () => {
    await renderNotes();
    const curve = "380ms cubic-bezier(0.3, 0.7, 0.2, 1)";
    expect(screen.getByTestId("notes-clov").style.transition).toContain(curve);
    expect(screen.getByTestId("notes-toolbar").parentElement!.style.transition)
      .toContain(curve);
  });

  it("the skeleton fades out at 720ms, under content that enters later", async () => {
    render(<ToastProvider><Library /></ToastProvider>);
    const skeleton = await screen.findByTestId("library-skeleton");
    expect(skeleton.style.animation).toBe("sapSkelOut 260ms ease 720ms both");
  });

  it("reduced motion is honoured, scoped to these pages", () => {
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

  it("the stylesheets resolve every face through the repo's variables", () => {
    // next/font registers each face under a generated name, so a bare 'Aleo'
    // would silently render Times. The Library sets its faces inline (the test
    // above); the editor's stylesheet is where the three var()s live.
    expect(PORTED_CSS).not.toMatch(/font-family:[^;]*'Aleo'/);
    expect(PORTED_CSS).not.toMatch(/font-family:[^;]*'SUSE'/);
    expect(PORTED_CSS).not.toMatch(/font-family:[^;]*'IBM Plex Mono'/);
    expect(NOTES_CSS).toContain("var(--font-serif)");
    expect(NOTES_CSS).toContain("var(--font-sans)");
    expect(NOTES_CSS).toContain("var(--font-mono)");
  });

  it("the Library title is Aleo at the design's 34px", async () => {
    await renderLibrary();
    const h1 = screen.getByRole("heading", { name: "Library", level: 1 });
    expect(h1.style.fontSize).toBe("34px");
    expect(h1.style.fontWeight).toBe("600");
    expect(h1.style.fontFamily).toContain("--font-serif");
  });
});

// ── the editor's own stylesheet ─────────────────────────────────────────────

describe("the notes editor's styles were ported, not reinvented", () => {
  it("carries every block selector the design styles", () => {
    // Each block's own class, wherever the design scopes it from.
    for (const cls of [
      "blk", "blk-h", "blk-x", "math", "imath", "mslot", "mslot-on", "mgrp",
      "mcaret", "mq-pop", "mq-syms", "mx-grid", "mx-out", "tbl-bar", "tbl-edit",
      "check", "tg-body", "tg-arrow", "qa-q", "qa-a", "fc-face", "fc-back",
      "code-ed", "pl-svg", "ch-svg", "pl-row", "ch-row", "pl-sl", "g-kinds",
      "g-btn", "pl-zoom", "pl-legend", "ch-tip", "ch-add", "ch-grip", "pie-h",
    ]) {
      expect(NOTES_CSS.includes(`.${cls}`), `.${cls} missing from notes-editor.css`)
        .toBe(true);
      // And the design styles it too, so nothing here was invented.
      expect(NOTES_DESIGN.includes(`.${cls}`), `.${cls} is not in the design`).toBe(true);
    }
  });

  it("keeps the editor's type scale exactly", () => {
    // The design's own values for the document's own text.
    expect(NOTES_CSS).toContain("[data-notes] h1 {");
    expect(NOTES_CSS).toMatch(/\[data-notes\] h1 \{[^}]*font-size: 36px/);
    expect(NOTES_CSS).toMatch(/\[data-notes\] h2 \{[^}]*font-size: 26px/);
    expect(NOTES_CSS).toMatch(/\[data-notes\] p \{[^}]*font-size: 17px/);
  });
});
