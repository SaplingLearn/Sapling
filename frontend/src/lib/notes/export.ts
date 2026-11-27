/**
 * Download the notes as a web page or as Markdown.
 *
 * Both are produced from the editor's own DOM rather than from stored HTML,
 * so what is exported is what is on screen — a flipped flashcard, a revealed
 * answer and an edited table included.
 *
 * Ported from `exportHTML` / `exportMD` in `designs/Sapling Notes.dc.html`.
 */

/** The chrome that only makes sense while editing. */
const EDITOR_ONLY = [
  ".blk-x", ".tbl-bar", ".tbl-edit", ".g-head", ".g-side",
  ".pl-zoom", ".ch-tip", ".mq-pop", ".ch-add", ".ch-grip", ".pie-h", ".mslot-key",
].join(", ");

function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * A standalone web page of the notes.
 *
 * KaTeX's stylesheet is linked from the CDN rather than inlined: the file is
 * opened outside the app, where our own stylesheet does not exist, and a
 * 300 KB inline copy in every export is worse than a link that degrades to
 * plain glyphs offline.
 */
export function exportHTML(editor: HTMLElement, title: string, meta: string): string {
  const copy = editor.cloneNode(true) as HTMLElement;
  copy.querySelectorAll(EDITOR_ONLY).forEach(n => n.remove());
  copy.querySelectorAll("[contenteditable]").forEach(n => n.removeAttribute("contenteditable"));
  const t = esc(title);
  return `<!doctype html><html><head><meta charset="utf-8"><title>${t}</title>`
    + '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">'
    + "<style>body{font-family:Georgia,serif;max-width:760px;margin:48px auto;padding:0 24px;"
    + "line-height:1.6;color:#1A1814}h1,h2,h3{line-height:1.2}"
    + "table{border-collapse:collapse;width:100%}"
    + "td,th{border:1px solid #DDD6C8;padding:6px 10px;text-align:left}"
    + "pre{background:#1F2419;color:#E8EDE0;padding:14px;border-radius:8px;overflow:auto}"
    + ".math{text-align:center;margin:12px 0}.blk{margin:16px 0}svg{max-width:100%;height:auto}"
    + ".fc-back,.qa-a{border-top:1px dashed #CCC;padding-top:8px}"
    + ".fc-face,.qa-a{display:block!important;transform:none!important}</style></head>"
    + `<body><h1>${t}</h1><p style="color:#6F6857">${esc(meta)}</p>${copy.innerHTML}</body></html>`;
}

/** The inline text of a node, as Markdown. */
function inline(n: Node): string {
  return [...n.childNodes].map(x => {
    if (x.nodeType === 3) return (x as Text).data.replace(/​/g, "");
    const el = x as HTMLElement;
    if (el.classList?.contains("imath")) return `$${el.getAttribute("data-tex")}$`;
    switch (el.tagName) {
      case "STRONG": case "B": return `**${inline(el)}**`;
      case "EM": case "I": return `*${inline(el)}*`;
      case "CODE": return `\`${el.textContent}\``;
      case "A": return `[${inline(el)}](${el.getAttribute("href")})`;
      case "BR": return "";
      default: return inline(el);
    }
  }).join("");
}

/** The notes as Markdown: GFM tables, task lists, `$$` display math. */
export function exportMarkdown(editor: HTMLElement, title: string): string {
  const out: string[] = [`# ${title}`];

  [...editor.children].forEach(node => {
    const el = node as HTMLElement;
    const tag = el.tagName;

    if (/^H[1-3]$/.test(tag)) {
      // The document title is the `#`, so the body's H1s start at `##`.
      out.push("#".repeat(+tag[1] + (tag === "H1" ? 1 : 0)) + " " + inline(el));
      return;
    }
    if (tag === "P") {
      const s = inline(el).trim();
      if (s) out.push(s);
      return;
    }
    if (tag === "UL" || tag === "OL") {
      const checklist = el.classList.contains("check");
      out.push([...el.children].map((li, i) => {
        const bullet = tag === "OL"
          ? `${i + 1}. `
          : checklist
            ? ((li as HTMLElement).getAttribute("data-done") === "1" ? "- [x] " : "- [ ] ")
            : "- ";
        return bullet + inline(li).replace(/^✓/, "").trim();
      }).join("\n"));
      return;
    }
    if (tag === "BLOCKQUOTE") { out.push(`> ${inline(el)}`); return; }
    if (tag === "PRE") { out.push("```\n" + (el.textContent || "").trim() + "\n```"); return; }
    if (tag === "HR") { out.push("---"); return; }
    if (el.classList?.contains("math")) {
      out.push(`$$\n${el.getAttribute("data-tex")}\n$$`);
      return;
    }
    if (el.querySelector?.("table")) {
      const trs = [...el.querySelectorAll("tr")];
      const rows = trs.map(tr => `| ${[...tr.children].map(c => inline(c).trim()).join(" | ")} |`);
      if (rows.length) rows.splice(1, 0, `|${" --- |".repeat(trs[0].children.length)}`);
      out.push(rows.join("\n"));
      return;
    }
    // Anything else (a graph, a flashcard) contributes its text, with the
    // editor's own glyphs stripped.
    const s = (el.innerText || el.textContent || "").replace(/[×✓]/g, "").trim();
    if (s) out.push(s);
  });

  return `${out.join("\n\n")}\n`;
}

/** Hand the browser a file to save. */
export function download(name: string, text: string, type: string): void {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** A file name from a document title, with what a filesystem refuses removed. */
export function fileBase(title: string): string {
  return title.replace(/[\\/:*?"<>|]+/g, "").trim() || "Notes";
}

/**
 * Print to PDF through a new window. There is no PDF writer in the browser,
 * and the print dialog's "Save as PDF" is what the design's PDF item means.
 * A blocked popup falls back to downloading the HTML.
 */
export function printPDF(html: string, fallbackName: string): void {
  const w = window.open("", "_blank");
  if (!w) {
    download(`${fallbackName}.html`, html, "text/html");
    return;
  }
  w.document.write(html);
  w.document.close();
  // The stylesheet and the fonts need a moment before the page is worth printing.
  setTimeout(() => {
    try { w.focus(); w.print(); } catch { /* the user closed it */ }
  }, 600);
}
