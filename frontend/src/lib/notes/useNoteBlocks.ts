"use client";
/**
 * What a click inside the editor does to a block: tick a checklist item, show
 * an answer, switch a matrix between 2×2 and 3×3, add or remove a table row
 * or column, and remove a block.
 *
 * The editor is a `contentEditable`, so every block is markup carrying
 * `data-act` attributes, and this is the one delegated handler that reads
 * them — which is why a block that comes back from a save behaves without
 * being re-wired.
 *
 * Ported from `onEdClick` / `onEdInput` in `designs/Sapling Notes.dc.html`.
 */
import React from "react";

import { BLOCKS, matrixOutput } from "./blocks";
import { useLatest } from "./useLatest";

export interface NoteBlocks {
  /** Delegated click handler for the editor. */
  onClick: (e: React.MouseEvent) => void;
  /** Delegated input handler, for the inputs blocks contain. */
  onInput: (e: React.FormEvent) => void;
}

export interface NoteBlocksInput {
  onChange: () => void;
  /** Re-renders graphs and equations after a block is replaced. */
  refresh: () => void;
}

/** One block action. Returning false means nothing changed. */
type Action = (btn: HTMLElement, blk: HTMLElement | null) => boolean | void;

const remove: Action = (btn, blk) => {
  if (!blk) return false;
  // The table's own "×" leaves edit mode; "Delete table" in its bar removes it.
  if (blk.dataset.blk === "table" && btn.classList.contains("blk-x")) {
    blk.dataset.edit = "0";
    return true;
  }
  // The empty paragraph the block was inserted with goes too, so removing a
  // block does not leave a gap behind.
  const next = blk.nextSibling as HTMLElement | null;
  if (next && next.tagName === "P" && !next.textContent?.trim()) next.remove();
  blk.remove();
  return true;
};

const toggleCheck: Action = btn => {
  const li = btn.closest("li");
  if (!li) return false;
  li.setAttribute("data-done", li.getAttribute("data-done") === "1" ? "0" : "1");
};

const toggleOpen: Action = (btn, blk) => {
  if (!blk) return false;
  const open = blk.getAttribute("data-open") === "1" ? "0" : "1";
  blk.setAttribute("data-open", open);
  if (blk.dataset.blk === "qa") btn.textContent = open === "1" ? "Hide Answer" : "Show Answer";
};

const resizeMatrix = (n: 2 | 3): Action => (_btn, blk) => {
  if (!blk) return false;
  const tmp = document.createElement("div");
  tmp.innerHTML = BLOCKS.matrix(n);
  const replacement = tmp.firstChild;
  if (!replacement) return false;
  blk.replaceWith(replacement);
};

const toggleTableEdit: Action = (_btn, blk) => {
  if (!blk) return false;
  blk.dataset.edit = blk.dataset.edit === "1" ? "0" : "1";
};

const addRow: Action = (_btn, blk) => {
  const body = blk?.querySelector("tbody");
  if (!blk || !body) return false;
  const cols = blk.querySelectorAll("thead th").length;
  const tr = document.createElement("tr");
  tr.innerHTML = "<td><br></td>".repeat(cols);
  body.appendChild(tr);
};

const removeRow: Action = (_btn, blk) => {
  const rows = blk?.querySelectorAll("tbody tr");
  // The last row never goes: a table with a head and no body is not a table.
  if (!rows || rows.length <= 1) return false;
  rows[rows.length - 1].remove();
};

const addColumn: Action = (_btn, blk) => {
  if (!blk) return false;
  blk.querySelector("thead tr")?.insertAdjacentHTML("beforeend", "<th>New column</th>");
  blk.querySelectorAll("tbody tr").forEach(
    tr => tr.insertAdjacentHTML("beforeend", "<td><br></td>"),
  );
};

const removeColumn: Action = (_btn, blk) => {
  if (!blk || blk.querySelectorAll("thead th").length <= 1) return false;
  blk.querySelectorAll("tr").forEach(tr => tr.lastElementChild?.remove());
};

const ACTIONS: Record<string, Action> = {
  del: remove,
  check: toggleCheck,
  open: toggleOpen,
  mx2: resizeMatrix(2),
  mx3: resizeMatrix(3),
  tedit: toggleTableEdit,
  row: addRow,
  delrow: removeRow,
  col: addColumn,
  delcol: removeColumn,
};

export function useNoteBlocks({ onChange, refresh }: NoteBlocksInput): NoteBlocks {
  const changeRef = useLatest(onChange);
  const refreshRef = useLatest(refresh);

  const onClick = React.useCallback((e: React.MouseEvent) => {
    const btn = (e.target as HTMLElement).closest?.("[data-act]") as HTMLElement | null;
    if (!btn) return;
    const act = btn.getAttribute("data-act") || "";
    // The graph block has its own handler; its actions all start `g-`.
    if (act.startsWith("g-")) return;
    const run = ACTIONS[act];
    if (!run) return;

    e.preventDefault();
    if (run(btn, btn.closest(".blk") as HTMLElement | null) === false) return;
    refreshRef.current();
    changeRef.current();
  }, [changeRef, refreshRef]);

  const onInput = React.useCallback((e: React.FormEvent) => {
    const el = e.target as HTMLElement;
    if (el?.tagName === "INPUT") {
      const field = el as HTMLInputElement;
      // The VALUE ATTRIBUTE, not the property: only the attribute survives
      // `innerHTML` being saved and read back.
      field.setAttribute("value", field.value);

      const blk = field.closest(".blk") as HTMLElement | null;
      if (blk?.dataset.blk === "matrix") {
        const o = matrixOutput(
          [...blk.querySelectorAll<HTMLInputElement>(".mx-grid input")].map(i => i.value),
        );
        const out = blk.querySelector(".mx-out");
        const note = blk.querySelector(".mx-note");
        if (out) out.innerHTML = o.out;
        if (note) note.textContent = o.note;
      }
    }
    changeRef.current();
  }, [changeRef]);

  return { onClick, onInput };
}
