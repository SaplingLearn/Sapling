/**
 * What the floating toolbar holds, and how it shrinks when Ask Clov opens.
 *
 * The design gives the toolbar two sizes rather than a scroll or a wrap: with
 * Clov open every control narrows, the style dropdown switches to short
 * labels, and alignment collapses from three buttons into one dropdown. Those
 * sizes are a table here so the component can stay layout.
 */
import type React from "react";

/** The icon paths the toolbar uses, from the design. */
export const PATHS = {
  undo: "M6 4L3 7l3 3M3 7h7.5a4 4 0 0 1 0 8H8",
  redo: "M12 4l3 3-3 3M15 7H7.5a4 4 0 0 0 0 8H10",
  ul: "M7 5h8M7 9h8M7 13h8M3.5 5h.01M3.5 9h.01M3.5 13h.01",
  ol: "M8 5h7M8 9h7M8 13h7M3 4l1-.5V7M3 10.5c.3-.6 1.7-.6 1.8.2.1.6-1.8 1.5-1.8 2.3h2",
  quote: "M4 6h3v3H5.5c0 1.5.5 2.5 1.5 3M11 6h3v3h-1.5c0 1.5.5 2.5 1.5 3",
  mark: "M10.5 3.5l4 4-6.5 6.5H4v-4zM3 16h12",
  code: "M6.5 5L2.5 9l4 4M11.5 5l4 4-4 4",
  link: "M7.5 10.5a3 3 0 0 0 4.2 0l2.6-2.6a3 3 0 0 0-4.2-4.2l-1 1"
    + "M10.5 7.5a3 3 0 0 0-4.2 0l-2.6 2.6a3 3 0 0 0 4.2 4.2l1-1",
  checklist: "M2.5 5l1.5 1.5L6.5 4M2.5 12l1.5 1.5L6.5 11M9 5.5h6.5M9 12.5h6.5",
  alignLeft: "M3 4.5h12M3 8h8M3 11.5h12M3 15h8",
  alignCenter: "M3 4.5h12M5 8h8M3 11.5h12M5 15h8",
  alignRight: "M3 4.5h12M7 8h8M3 11.5h12M7 15h8",
} as const;

/** The three alignments, in the order the design lists them. */
export const ALIGNMENTS: { tip: string; cmd: string; path: string }[] = [
  { tip: "Align left", cmd: "justifyLeft", path: PATHS.alignLeft },
  { tip: "Align center", cmd: "justifyCenter", path: PATHS.alignCenter },
  { tip: "Align right", cmd: "justifyRight", path: PATHS.alignRight },
];

/** The text styles the "Normal text" dropdown offers. */
export interface TextStyle {
  label: string;
  /** What `formatBlock` is given. */
  block: string;
  /** The tag `queryCommandValue("formatBlock")` reports. */
  tag: string;
  font: string;
  size: string;
  weight: number;
}

export const TEXT_STYLES: TextStyle[] = [
  { label: "Normal text", block: "<p>", tag: "p", font: "inherit", size: "15px", weight: 400 },
  {
    label: "Heading 1", block: "<h1>", tag: "h1",
    font: "var(--font-serif)", size: "22px", weight: 600,
  },
  {
    label: "Heading 2", block: "<h2>", tag: "h2",
    font: "var(--font-serif)", size: "19px", weight: 600,
  },
  { label: "Heading 3", block: "<h3>", tag: "h3", font: "inherit", size: "16px", weight: 700 },
  {
    label: "Quote", block: "<blockquote>", tag: "blockquote",
    font: "var(--font-serif)", size: "15px", weight: 400,
  },
];

/** The short label a style takes while Clov is open. */
const SHORT: Record<string, string> = {
  "Normal text": "Normal",
  "Heading 1": "H1",
  "Heading 2": "H2",
  "Heading 3": "H3",
};

export function styleLabel(style: TextStyle, clovOpen: boolean): string {
  return clovOpen ? SHORT[style.label] ?? style.label : style.label;
}

/**
 * Every size the toolbar and its header change between. `wide` is Clov closed.
 *
 * They are transitioned, not swapped: the design moves each one over 380 ms on
 * the same curve as the panel, so the toolbar appears to be squeezed by it.
 */
export interface ToolbarMetrics {
  button: string;
  padX: string;
  separator: string;
  outerPad: string;
  styleWidth: string;
  insertPadLeft: string;
  insertPadRight: string;
  top: string;
  navMax: string;
  /** The header's right edge: the panel's width, so it never slides under it. */
  headerRight: string;
  /** Share and Download lose their labels when there is no room. */
  headerButtonPad: string;
}

export const METRICS: Record<"wide" | "narrow", ToolbarMetrics> = {
  wide: {
    button: "36px", padX: "8px", separator: "6px", outerPad: "6px 8px",
    styleWidth: "148px", insertPadLeft: "10px", insertPadRight: "14px",
    top: "12px", navMax: "300px", headerRight: "0px", headerButtonPad: "14px",
  },
  narrow: {
    button: "30px", padX: "5px", separator: "3px", outerPad: "4px 5px",
    styleWidth: "108px", insertPadLeft: "8px", insertPadRight: "8px",
    top: "18px", navMax: "220px", headerRight: "440px", headerButtonPad: "0px",
  },
};

/**
 * What the header row's two sizes actually measure, in the browser, at the
 * design's own type and metrics (2026-11-27). They are constants because
 * they are consequences of `METRICS` and the labels, not of the window: the
 * bar and the actions are the same width at 1280 as at 1920.
 *
 * Reading them off the live DOM instead is what made the row flicker. Each
 * reading depended on the state it was being used to choose — collapse the
 * actions and the row looks roomier, which un-collapses them — so the layout
 * settled on whichever pass happened to run last.
 */
export const ROW_WIDTHS = {
  /** The bar with every label: the style name and "Insert". */
  wideBar: 937,
  /** The bar under `METRICS.narrow`, labels dropped. */
  narrowBar: 656,
  /** Share / Download / Finalize written out, plus the Regenerate icon. */
  wideActions: 371,
  /** The same four as icons, with Finalize keeping its word. */
  narrowActions: 227,
} as const;

/**
 * Narrowest corridor between the breadcrumb and the header actions that the
 * toolbar will still centre itself in. Below it the bar drops to its own row.
 * Sized off the bar's own natural width: `METRICS.narrow` measures ~656px
 * (the Clov-open case, which is the tight one — with Clov closed the bar is
 * wider but the corridor gains that panel's 440px back). The threshold sits
 * just above it so the bar is never left PARTLY squeezed: it either has the
 * room it wants in the header row, or it takes a row of its own and has it
 * there. At 480 the 1700-1800 band kept the bar in the header at two thirds
 * of its width, scrolling, when a full-width row was available below.
 */
export const TOOLBAR_MIN_CORRIDOR = 672;

/** The design's shared transition for everything the panel squeezes. */
export const SQUEEZE = "380ms cubic-bezier(0.3, 0.7, 0.2, 1)";

/** Which formatting commands are on right now. */
export interface Formats {
  bold: boolean;
  italic: boolean;
  underline: boolean;
  strikeThrough: boolean;
  insertUnorderedList: boolean;
  insertOrderedList: boolean;
  justifyLeft: boolean;
  justifyCenter: boolean;
  justifyRight: boolean;
  /** The block tag the caret is in, lowercased. */
  block: string;
}

export const NO_FORMATS: Formats = {
  bold: false, italic: false, underline: false, strikeThrough: false,
  insertUnorderedList: false, insertOrderedList: false,
  justifyLeft: false, justifyCenter: false, justifyRight: false, block: "",
};

/** Read the current formatting off the selection. */
export function readFormats(): Formats {
  const q = (c: string) => {
    try { return document.queryCommandState(c); } catch { return false; }
  };
  let block = "";
  try { block = String(document.queryCommandValue("formatBlock") || "").toLowerCase(); } catch {
    block = "";
  }
  return {
    bold: q("bold"),
    italic: q("italic"),
    underline: q("underline"),
    strikeThrough: q("strikeThrough"),
    insertUnorderedList: q("insertUnorderedList"),
    insertOrderedList: q("insertOrderedList"),
    justifyLeft: q("justifyLeft"),
    justifyCenter: q("justifyCenter"),
    justifyRight: q("justifyRight"),
    block,
  };
}

/** One toolbar control. */
export interface Tool {
  key: string;
  tip: string;
  /** A glyph-only button has no path; a path-only button has no label. */
  label?: string;
  path?: string;
  on?: boolean;
  font?: string;
  weight?: number;
  style?: React.CSSProperties["fontStyle"];
  decoration?: string;
  run: () => void;
}

export type ToolOrSeparator = Tool | { separator: true };

export const isSeparator = (t: ToolOrSeparator): t is { separator: true } =>
  "separator" in t;

export interface ToolsInput {
  formats: Formats;
  /** Runs a `document.execCommand`, restoring the selection first. */
  exec: (cmd: string, value?: string) => void;
  insertHTML: (html: string) => void;
  insertCode: () => void;
  insertLink: () => void;
  /** With Clov open, alignment moves into a dropdown of its own. */
  clovOpen: boolean;
}

/** Undo and redo, which sit before the style dropdown. */
export function leadingTools({ exec }: Pick<ToolsInput, "exec">): Tool[] {
  return [
    { key: "undo", tip: "Undo (Ctrl+Z)", path: PATHS.undo, run: () => exec("undo") },
    { key: "redo", tip: "Redo (Ctrl+Y)", path: PATHS.redo, run: () => exec("redo") },
  ];
}

/** Everything after the style dropdown, up to the equation button. */
export function mainTools(input: ToolsInput): ToolOrSeparator[] {
  const { formats: f, exec, insertHTML, insertCode, insertLink, clovOpen } = input;
  const tools: ToolOrSeparator[] = [
    {
      key: "bold", tip: "Bold (Ctrl+B)", label: "B", on: f.bold, weight: 700,
      run: () => exec("bold"),
    },
    {
      key: "italic", tip: "Italic (Ctrl+I)", label: "I", on: f.italic,
      style: "italic", font: "var(--font-serif)", weight: 400,
      run: () => exec("italic"),
    },
    {
      key: "underline", tip: "Underline (Ctrl+U)", label: "U", on: f.underline,
      decoration: "underline", weight: 400, run: () => exec("underline"),
    },
    {
      key: "strike", tip: "Strikethrough", label: "S", on: f.strikeThrough,
      decoration: "line-through", weight: 400, run: () => exec("strikeThrough"),
    },
    {
      key: "highlight", tip: "Highlight", path: PATHS.mark,
      run: () => exec("hiliteColor", "#F6E7B0"),
    },
    { key: "code", tip: "Inline code", path: PATHS.code, run: insertCode },
    { key: "link", tip: "Link (Ctrl+K)", path: PATHS.link, run: insertLink },
    { separator: true },
    {
      key: "ul", tip: "Bulleted list", path: PATHS.ul, on: f.insertUnorderedList,
      run: () => exec("insertUnorderedList"),
    },
    {
      key: "ol", tip: "Numbered list", path: PATHS.ol, on: f.insertOrderedList,
      run: () => exec("insertOrderedList"),
    },
    {
      key: "checklist", tip: "Checklist", path: PATHS.checklist,
      run: () => insertHTML("@checklist"),
    },
    { separator: true },
  ];

  // Clov closed, the three alignments fit; open, they become one dropdown
  // which the toolbar renders separately.
  if (!clovOpen) {
    ALIGNMENTS.forEach(a => tools.push({
      key: a.cmd,
      tip: a.tip,
      path: a.path,
      on: f[a.cmd as "justifyLeft" | "justifyCenter" | "justifyRight"],
      run: () => exec(a.cmd),
    }));
  }
  return tools;
}

/** Which alignment is currently on. */
export function currentAlignment(f: Formats) {
  return ALIGNMENTS.find(a => f[a.cmd as "justifyLeft" | "justifyCenter" | "justifyRight"])
    ?? ALIGNMENTS[0];
}

/** Which text style the caret is in. */
export function currentStyle(f: Formats): TextStyle {
  return TEXT_STYLES.find(s => s.tag === f.block) ?? TEXT_STYLES[0];
}
