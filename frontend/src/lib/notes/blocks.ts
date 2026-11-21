/**
 * The HTML of every block the Notes editor can insert.
 *
 * The editor is a `contentEditable`, so a block IS markup: these builders
 * produce exactly the shapes `library-notes.css` styles and `useNoteBlocks`
 * drives, and exactly the shapes that round-trip through a save and reload.
 *
 * Ported from `BLK` in `designs/Sapling Notes.dc.html`, verbatim apart from
 * the escaping helper being shared.
 */

/** Escape text that is going into markup. */
export function esc(s: unknown): string {
  return String(s ?? "").replace(/[&<>"]/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string
  ));
}

/** The remove button every block carries in its corner. */
export const X = '<button class="blk-x" contenteditable="false" data-act="del" '
  + 'title="Remove" aria-label="Remove block">×</button>';

/** A block's mono caps heading. */
const H = (t: string) => `<div class="blk-h" contenteditable="false">${t}</div>`;

/** A trailing empty paragraph, so there is always somewhere to type after a block. */
const TAIL = "<p><br></p>";

/** The determinant of a flat 2×2 or 3×3 matrix. */
export function det(m: number[]): number {
  if (m.length === 4) return m[0] * m[3] - m[1] * m[2];
  return m[0] * (m[4] * m[8] - m[5] * m[7])
    - m[1] * (m[3] * m[8] - m[5] * m[6])
    + m[2] * (m[3] * m[7] - m[4] * m[6]);
}

/** What the matrix calculator says under its grid. */
export function matrixOutput(values: string[]): { out: string; note: string } {
  const n = values.map(v => parseFloat(v));
  if (n.some(Number.isNaN)) return { out: "det = <b>?</b>", note: "Fill every entry." };
  const d = Math.round(det(n) * 1000) / 1000;
  return {
    out: `det = <b>${d}</b>`,
    note: d === 0
      ? "Zero determinant: not invertible, columns are dependent."
      : `Invertible. Scales area by ${Math.abs(d)}${d < 0 ? " and flips orientation" : ""}.`,
  };
}

export const BLOCKS = {
  /** A centred display equation, opened empty so the palette offers itself. */
  math: (tex = "") =>
    `<div class="math" contenteditable="false" data-tex="${esc(tex)}"></div>${TAIL}`,

  matrix: (n: 2 | 3 = 2, values?: string[]) => {
    const v = values
      ?? (n === 2 ? ["3", "1", "2", "4"] : ["2", "0", "1", "1", "3", "2", "1", "1", "1"]);
    const o = matrixOutput(v);
    return `<div class="blk" contenteditable="false" data-blk="matrix" data-n="${n}">${X}`
      + `${H("Matrix Calculator")}<div class="mx">`
      + `<div class="mx-grid" style="grid-template-columns: repeat(${n}, auto);">`
      + v.map(x => `<input type="text" inputmode="decimal" value="${esc(x)}" `
        + 'aria-label="Matrix entry">').join("")
      + `</div><div><div class="mx-out">${o.out}</div>`
      + `<div class="mx-note">${esc(o.note)}</div></div></div>`
      + `<div class="tbl-bar"><button class="sbtn ${n === 2 ? "on" : ""}" data-act="mx2">2 × 2</button>`
      + `<button class="sbtn ${n === 3 ? "on" : ""}" data-act="mx3">3 × 3</button></div></div>${TAIL}`;
  },

  table: (head?: string[], rows?: string[][]) => {
    const h = head ?? ["Term", "Meaning", "Example"];
    const r = rows ?? [["", "", ""], ["", "", ""]];
    return '<div class="blk" data-blk="table" data-edit="0">' + X
      + '<button class="tbl-edit" contenteditable="false" data-act="tedit">Edit</button>'
      + `<table><thead><tr>${h.map(c => `<th>${c}</th>`).join("")}</tr></thead>`
      + `<tbody>${r.map(row => `<tr>${row.map(c => `<td>${c || "<br>"}</td>`).join("")}</tr>`).join("")}</tbody>`
      + '</table><div class="tbl-bar" contenteditable="false">'
      + '<button class="sbtn" data-act="row">+ Row</button>'
      + '<button class="sbtn" data-act="col">+ Column</button>'
      + '<button class="sbtn" data-act="delrow">− Row</button>'
      + '<button class="sbtn" data-act="delcol">− Column</button>'
      + '<span style="flex:1"></span>'
      + '<button class="sbtn tbl-del" data-act="del">Delete table</button>'
      + '<button class="sbtn tbl-done" data-act="tedit">Done</button>'
      + `</div></div>${TAIL}`;
  },

  check: (items?: string[]) =>
    '<ul class="check">'
    + (items ?? ["First thing to review", "Second thing to review"])
      .map(i => '<li data-done="0"><span class="box" contenteditable="false" '
        + `data-act="check">✓</span><span>${i}</span></li>`).join("")
    + "</ul>",

  toggle: (title?: string, body?: string) =>
    '<div class="blk" data-blk="toggle" data-open="1">' + X
    + '<div class="tg-head"><button class="tg-arrow" contenteditable="false" '
    + 'data-act="open" aria-label="Show or hide">▶</button>'
    + `<div class="tg-title">${title || "Worked example"}</div></div>`
    + `<div class="tg-body"><p>${body || "Write the steps here."}</p></div></div>${TAIL}`,

  qa: (q?: string, a?: string) =>
    '<div class="blk" data-blk="qa" data-open="0">' + X + H("Practice Question")
    + `<div class="qa-q">${q || "Write a question to test yourself."}</div>`
    + '<div class="tbl-bar" contenteditable="false">'
    + '<button class="sbtn" data-act="open">Show Answer</button></div>'
    + `<div class="qa-a">${a || "Write the answer here."}</div></div>${TAIL}`,

  card: (front?: string, back?: string) =>
    '<div class="blk" data-blk="card" data-open="0">' + X + H("Flashcard")
    + `<div class="fc-face fc-front">${front || "Front"}</div>`
    + `<div class="fc-face fc-back">${back || "Back"}</div>`
    + '<div class="tbl-bar" contenteditable="false">'
    + `<button class="sbtn" data-act="open">Flip Card</button></div></div>${TAIL}`,

  code: () =>
    '<div class="blk code" data-blk="code">' + X + H("Code")
    + '<pre class="code-ed" spellcheck="false"><code>// Type your code here\n</code></pre>'
    + `</div>${TAIL}`,

  divider: () => `<hr>${TAIL}`,
};

/** What the Insert menu lists, in the design's order. */
export interface BlockMenuItem {
  label: string;
  desc: string;
  glyph: string;
  bg: string;
  fg: string;
  html: () => string;
}

export const BLOCK_MENU: BlockMenuItem[] = [
  {
    label: "Math Equation", desc: "A centered formula line", glyph: "∑",
    bg: "#F4F1EA", fg: "#1A1814", html: () => BLOCKS.math(),
  },
  {
    label: "Matrix Calculator", desc: "Live determinant, 2×2 or 3×3", glyph: "[ ]",
    bg: "#EBF0E1", fg: "#2F4417", html: () => BLOCKS.matrix(2),
  },
  {
    label: "Table", desc: "Rows and columns you can extend", glyph: "▦",
    bg: "#EFEBE2", fg: "#3F3B31", html: () => BLOCKS.table(),
  },
  {
    label: "Checklist", desc: "Tick items off as you review", glyph: "✓",
    bg: "#EBF0E1", fg: "#2F4417", html: () => BLOCKS.check(),
  },
  {
    label: "Toggle Section", desc: "Hide worked examples until needed", glyph: "▸",
    bg: "#F4F1EA", fg: "#3F3B31", html: () => BLOCKS.toggle(),
  },
  {
    label: "Practice Question", desc: "Question with a hidden answer", glyph: "?",
    bg: "#FBF1DC", fg: "#8A6420", html: () => BLOCKS.qa(),
  },
  {
    label: "Flashcard", desc: "Front and back you can flip", glyph: "⇄",
    bg: "#F6E3E1", fg: "#8E2F29", html: () => BLOCKS.card(),
  },
  {
    label: "Code Block", desc: "Type or paste code", glyph: "{ }",
    bg: "#EFEBE2", fg: "#3F3B31", html: () => BLOCKS.code(),
  },
  {
    label: "Divider", desc: "Separate sections", glyph: "—",
    bg: "#F4F1EA", fg: "#6F6857", html: () => BLOCKS.divider(),
  },
];

/** The five graph kinds the Insert menu offers above the block list. */
export const GRAPH_KINDS: { key: "fn" | "bar" | "line" | "scatter" | "pie"; label: string; icon: string }[] = [
  { key: "fn", label: "Function", icon: "M2 15c3-1 4-10 7-10s4 9 7 10M2 9h14" },
  { key: "bar", label: "Bar", icon: "M3 15V9M7.5 15V4M12 15V7M16 15V11M1.5 15.5h15" },
  { key: "line", label: "Line", icon: "M2 13l4-4 3 2 6-7M1.5 15.5h15" },
  {
    key: "scatter", label: "Scatter",
    icon: "M4 13h.01M7 9h.01M10 11h.01M13 5h.01M15 8h.01M1.5 15.5h15",
  },
  { key: "pie", label: "Pie", icon: "M9 2a7 7 0 1 0 7 7H9z M11 1.5a6 6 0 0 1 5.5 5.5H11z" },
];
