"use client";
/**
 * In-place equation editing inside the notes editor.
 *
 * KaTeX renders the equation; a hidden input takes the keystrokes. Clicking a
 * rendered glyph reads the `data-pos` that `slotTex` stamped on it and opens
 * exactly that span of the LaTeX for editing — which is what lets a student
 * click a numerator they have already filled and keep typing in it.
 *
 * Ported from the math half of `designs/notes-graph.js`; the slot arithmetic
 * lives in `mathSlots.ts` and is tested there.
 */
import React from "react";

import {
  fractionAt, insertTpl, nextBox, slotCtx, slotTex, toTex, type MathCtx,
} from "./mathSlots";
import { useLatest } from "./useLatest";

type Katex = {
  render: (tex: string, el: HTMLElement, opts: Record<string, unknown>) => void;
  renderToString: (tex: string, opts: Record<string, unknown>) => string;
};

const KATEX_OPTS = { throwOnError: false, trust: true, strict: false } as const;

let katexPromise: Promise<Katex> | null = null;

/**
 * KaTeX, loaded once and lazily. It is ~300 KB and only the notes page needs
 * it, so it never reaches the rest of the bundle.
 */
export function loadKatex(): Promise<Katex> {
  if (!katexPromise) {
    katexPromise = Promise.all([
      import("katex"),
      import("katex/dist/katex.min.css"),
    ]).then(([m]) => (m.default ?? m) as unknown as Katex);
  }
  return katexPromise;
}

/** Render one `.math` / `.imath` element from its `data-tex`. */
export function renderMath(katex: Katex, el: HTMLElement, active?: MathCtx | null): void {
  const raw = el.getAttribute("data-tex") || "";
  const block = el.classList.contains("math");
  let tex = slotTex(raw);

  if (active && !active.root) {
    const inner = raw.slice(active.start, active.end);
    tex = slotTex(raw.slice(0, active.start))
      + `\\htmlClass{mslot-on}{${inner.trim() ? inner : "\\phantom{0}"}}`
      + slotTex(raw.slice(active.end), active.end);
  }

  try {
    katex.render(
      tex || "\\htmlData{pos=-1}{\\htmlClass{mslot}{\\phantom{0}}}",
      el,
      { ...KATEX_OPTS, displayMode: block },
    );
  } catch {
    // A tex string KaTeX cannot parse at all still has to show as something.
    el.textContent = tex;
  }
  el.classList.toggle("m-empty", !raw);
}

/** Render every equation in `root`, filling in `data-tex` for a pasted one. */
export function renderAllMath(katex: Katex, root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>(".math, .imath").forEach(el => {
    if (!el.hasAttribute("data-tex")) el.setAttribute("data-tex", toTex(el.textContent || ""));
    el.setAttribute("contenteditable", "false");
    renderMath(katex, el);
  });
}

export interface NoteMath {
  /** Open an equation for editing; `pos` is a clicked slot, 0 for the whole thing. */
  open: (el: HTMLElement, pos?: number) => void;
  /** Finish editing, re-render, and drop an inline equation left empty. */
  close: () => void;
  /** The equation being edited, if any. */
  active: HTMLElement | null;
  /** The symbol palette is offered only for an equation with nothing in it yet. */
  paletteOpen: boolean;
  /** Insert a template from the palette. */
  insert: (tpl: string) => void;
  /** Render a palette button's preview. */
  preview: (tex: string) => string;
  /** Re-render everything, e.g. after loading or inserting markup. */
  refresh: () => void;
  /** Where the palette should sit, in the editor's own coordinates. */
  palettePos: { left: number; top: number };
}

export interface NoteMathInput {
  /** The contenteditable the equations live in. */
  rootRef: React.RefObject<HTMLElement | null>;
  /** Called whenever an equation changes, so the page can autosave. */
  onChange: () => void;
  /** Editing is off while the notes are finalized. */
  readOnly: boolean;
}

export function useNoteMath({ rootRef, onChange, readOnly }: NoteMathInput): NoteMath {
  const [katex, setKatex] = React.useState<Katex | null>(null);
  const [active, setActive] = React.useState<HTMLElement | null>(null);
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const [palettePos, setPalettePos] = React.useState({ left: 0, top: 0 });

  // The hidden input that receives the keystrokes while an equation is open.
  const keyRef = React.useRef<HTMLInputElement | null>(null);
  const ctxRef = React.useRef<MathCtx | null>(null);
  const activeRef = React.useRef<HTMLElement | null>(null);
  const changeRef = useLatest(onChange);

  React.useEffect(() => { void loadKatex().then(setKatex); }, []);

  const rawOf = (el: HTMLElement) => el.getAttribute("data-tex") || "";

  /** Re-render the open equation, showing the caret inside the open span. */
  const paint = React.useCallback(() => {
    const el = activeRef.current;
    const key = keyRef.current;
    if (!el || !katex) return;
    const raw = rawOf(el);
    const ctx = ctxRef.current;

    if (!ctx) { renderMath(katex, el); return; }

    const caretAbs = ctx.start + (key ? key.selectionStart ?? 0 : ctx.end - ctx.start);
    // A caret drawn in the middle of a control sequence would split its name,
    // so it is left out in that one case rather than corrupting the render.
    const safe = !/\\[a-zA-Z]*$/.test(raw.slice(0, caretAbs));
    const caret = "\\htmlClass{mcaret}{\\vphantom{X}}";

    let tex: string;
    if (ctx.root) {
      tex = safe
        ? slotTex(raw.slice(0, caretAbs)) + caret + slotTex(raw.slice(caretAbs), caretAbs)
        : slotTex(raw);
      if (!raw) tex = `${caret}\\htmlClass{mslot}{\\phantom{0}}`;
    } else {
      const inner = raw.slice(ctx.start, ctx.end);
      const body = inner.trim()
        ? (safe
          ? slotTex(raw.slice(ctx.start, caretAbs), ctx.start)
            + caret + slotTex(raw.slice(caretAbs, ctx.end), caretAbs)
          : slotTex(inner, ctx.start))
        : `${caret}\\phantom{0}`;
      tex = slotTex(raw.slice(0, ctx.start))
        + `\\htmlClass{mslot-on}{${body}}`
        + slotTex(raw.slice(ctx.end), ctx.end);
    }

    try {
      katex.render(
        tex || "\\htmlClass{mslot}{\\phantom{0}}",
        el,
        { ...KATEX_OPTS, displayMode: el.classList.contains("math") },
      );
    } catch {
      el.textContent = raw;
    }
    el.classList.toggle("m-empty", !raw);
  }, [katex]);

  /** Point the hidden input at a span of the source and focus it. */
  const setCtx = React.useCallback((ctx: MathCtx, caret: number) => {
    const el = activeRef.current;
    const key = keyRef.current;
    if (!el || !key) return;
    const raw = rawOf(el);
    ctxRef.current = ctx;
    key.value = raw.slice(ctx.start, ctx.end);
    const c = Math.max(0, Math.min(key.value.length, caret));
    key.focus();
    key.setSelectionRange(c, c);
    paint();
  }, [paint]);

  const rootCtx = React.useCallback((caret?: number) => {
    const el = activeRef.current;
    if (!el) return;
    const raw = rawOf(el);
    setCtx({ start: 0, end: raw.length, root: true }, caret ?? raw.length);
  }, [setCtx]);

  /** Write the hidden input's value back into the equation's source. */
  const commit = React.useCallback(() => {
    const el = activeRef.current;
    const key = keyRef.current;
    const ctx = ctxRef.current;
    if (!el || !key || !ctx) return;
    const raw = rawOf(el);
    el.setAttribute("data-tex", raw.slice(0, ctx.start) + key.value + raw.slice(ctx.end));
    ctxRef.current = { ...ctx, end: ctx.start + key.value.length };
    paint();
  }, [paint]);

  const close = React.useCallback(() => {
    const el = activeRef.current;
    activeRef.current = null;
    ctxRef.current = null;
    setActive(null);
    setPaletteOpen(false);
    if (keyRef.current) { keyRef.current.remove(); keyRef.current = null; }
    if (!el) return;
    el.classList.remove("m-on");
    // An inline equation the student opened and left empty is removed, so a
    // mis-click never leaves an invisible chip behind in the text.
    if (!rawOf(el) && el.classList.contains("imath")) el.remove();
    else if (katex) renderMath(katex, el);
    changeRef.current();
  }, [katex, changeRef]);

  const insert = React.useCallback((tpl: string) => {
    const key = keyRef.current;
    const el = activeRef.current;
    if (!key || !el) return;
    if (!ctxRef.current) rootCtx();
    const ctx = ctxRef.current;
    if (!ctx) return;
    const out = insertTpl(
      rawOf(el), ctx, key.selectionStart ?? 0, key.selectionEnd ?? 0, tpl,
    );
    el.setAttribute("data-tex", out.raw);
    setCtx(out.ctx, out.caret);
    setPaletteOpen(false);
    key.focus();
  }, [rootCtx, setCtx]);

  const open = React.useCallback((el: HTMLElement, pos = 0) => {
    if (readOnly) return;
    const root = rootRef.current;
    if (!root) return;
    if (activeRef.current && activeRef.current !== el) close();

    activeRef.current = el;
    setActive(el);
    el.classList.add("m-on");

    if (!keyRef.current) {
      const key = document.createElement("input");
      key.className = "mslot-key";
      key.setAttribute("aria-label", "Write math");
      key.autocomplete = "off";
      key.spellcheck = false;
      root.appendChild(key);
      keyRef.current = key;

      key.addEventListener("input", e => { e.stopPropagation(); commit(); });
      key.addEventListener("keyup", e => {
        if (/Arrow|Home|End/.test((e as KeyboardEvent).key)) paint();
      });
      /** Tab / Shift+Tab, and the arrow keys that step between boxes. */
      const moveBox = (ev: KeyboardEvent, back: boolean): void => {
        const cur = activeRef.current;
        if (!cur) return;
        ev.preventDefault();
        const to = nextBox(rawOf(cur), ctxRef.current, key.selectionStart ?? 0, back);
        if (to) setCtx(to.ctx, to.caret);
      };

      /** Enter or Escape: finish, and put the text caret after the equation. */
      const finish = (ev: KeyboardEvent): void => {
        const finished = activeRef.current;
        ev.preventDefault();
        close();
        if (!finished?.isConnected) return;
        const sel = window.getSelection();
        const range = document.createRange();
        range.setStartAfter(finished);
        range.collapse(true);
        sel?.removeAllRanges();
        sel?.addRange(range);
      };

      /** `/` after a term turns it into a fraction. */
      const makeFraction = (ev: KeyboardEvent): void => {
        const frac = fractionAt(key.value, key.selectionStart ?? 0);
        if (!frac) return;
        ev.preventDefault();
        const caret = key.selectionStart ?? 0;
        key.value = key.value.slice(0, frac.from) + key.value.slice(caret);
        key.setSelectionRange(frac.from, frac.from);
        commit();
        insert(`\\frac{${frac.term}}{}`);
      };

      key.addEventListener("keydown", e => {
        const ev = e as KeyboardEvent;
        ev.stopPropagation();
        if (!activeRef.current) return;

        if (ev.key === "Tab") { moveBox(ev, ev.shiftKey); return; }
        if (ev.key === "Enter" || ev.key === "Escape") { finish(ev); return; }

        const ctx = ctxRef.current;
        if (!ctx || ctx.root) {
          // At the root only the two structure shortcuts apply.
          if (ev.key === "^" || ev.key === "_") { ev.preventDefault(); insert(`${ev.key}{}`); }
          else if (ev.key === "/") makeFraction(ev);
          return;
        }

        const atEnd = key.selectionStart === key.value.length;
        const atStart = key.selectionStart === 0;
        if (ev.key === "ArrowRight" && atEnd) { moveBox(ev, false); return; }
        if (ev.key === "ArrowLeft" && atStart) {
          ev.preventDefault();
          rootCtx(Math.max(0, ctx.start - 1));
          return;
        }
        if (ev.key === "Backspace" && !key.value) {
          // Backspacing out of an empty slot steps back into the equation.
          ev.preventDefault();
          rootCtx(ctx.start - 1);
          return;
        }
        if (ev.key === "/") { makeFraction(ev); return; }
        if (ev.key === "^" || ev.key === "_") { ev.preventDefault(); insert(`${ev.key}{}`); }
      });
    }

    // Position the palette under the equation, clamped inside the editor.
    const rootBox = root.getBoundingClientRect();
    const box = el.getBoundingClientRect();
    const k = rootBox.width / root.offsetWidth || 1;
    const width = 520;
    setPalettePos({
      left: Math.max(0, Math.min(
        root.offsetWidth - width,
        (box.left + box.width / 2 - rootBox.left) / k - width / 2,
      )),
      top: (box.bottom - rootBox.top) / k + 8,
    });
    if (keyRef.current) {
      keyRef.current.style.left = `${(box.left - rootBox.left) / k}px`;
      keyRef.current.style.top = `${(box.top - rootBox.top) / k}px`;
    }

    // The palette is for an equation with nothing in it: a filled one is
    // edited by clicking its parts.
    setPaletteOpen(!rawOf(el));

    const raw = rawOf(el);
    if (pos > 0) {
      const to = slotCtx(raw, pos);
      setCtx(to.ctx, to.caret);
    } else {
      const slots = raw.match(/\{\s*\}|\[\s*\]/g);
      if (slots) {
        const first = raw.search(/\{\s*\}|\[\s*\]/) + 1;
        const to = slotCtx(raw, first);
        setCtx(to.ctx, to.caret);
      } else {
        rootCtx();
      }
    }
  }, [readOnly, rootRef, close, commit, paint, rootCtx, setCtx, insert]);

  const refresh = React.useCallback(() => {
    const root = rootRef.current;
    if (root && katex) renderAllMath(katex, root);
  }, [rootRef, katex]);

  // Render whatever is in the editor once KaTeX is ready.
  React.useEffect(() => { refresh(); }, [refresh]);

  // A pointer anywhere outside the open equation and its palette finishes it.
  React.useEffect(() => {
    if (!active) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node | null;
      if (!t) return;
      if (active.contains(t) || t === keyRef.current) return;
      if ((t as HTMLElement).closest?.(".mq-pop")) return;
      close();
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [active, close]);

  const preview = React.useCallback((tex: string) => {
    if (!katex) return "";
    try {
      return katex.renderToString(tex, { ...KATEX_OPTS, displayMode: false });
    } catch {
      return "";
    }
  }, [katex]);

  return { open, close, active, paletteOpen, insert, preview, refresh, palettePos };
}
