"use client";
/**
 * The contenteditable itself: what is selected, what formatting is on, how a
 * command runs, and how markup gets inserted at the caret.
 *
 * `document.execCommand` is deprecated but not replaced — every browser still
 * implements it, and it is what gives a contenteditable undo that survives
 * programmatic edits. The alternative is a full editor framework, which the
 * handoff explicitly leaves open and which this does not need.
 */
import React from "react";

import { BLOCKS } from "./blocks";
import { useLatest } from "./useLatest";
import { NO_FORMATS, readFormats, type Formats } from "@/components/notes/toolbarModel";

export interface NoteEditor {
  formats: Formats;
  /** Run a command, restoring the selection the toolbar stole first. */
  exec: (cmd: string, value?: string) => void;
  /** Insert markup at the caret, replacing an empty paragraph if that is where we are. */
  insertHTML: (html: string) => void;
  insertCode: () => void;
  insertLink: () => void;
  /** Put the caret back where it was before the toolbar took focus. */
  restore: () => void;
  /** The selected text, or "". */
  selectedText: () => string;
  /** Re-read the formatting state, e.g. after a command. */
  sync: () => void;
  /** The last selection range, so a reply can replace exactly it. */
  lastRange: React.RefObject<Range | null>;
}

export interface NoteEditorInput {
  editorRef: React.RefObject<HTMLElement | null>;
  onChange: () => void;
  /** Re-renders inserted math and graphs. */
  afterInsert: () => void;
  readOnly: boolean;
}

export function useNoteEditor(input: NoteEditorInput): NoteEditor {
  const { editorRef, onChange, afterInsert, readOnly } = input;
  const [formats, setFormats] = React.useState<Formats>(NO_FORMATS);
  const lastRange = React.useRef<Range | null>(null);
  const changeRef = useLatest(onChange);
  const afterRef = useLatest(afterInsert);

  const sync = React.useCallback(() => {
    const ed = editorRef.current;
    const sel = window.getSelection();
    if (!ed || !sel || !sel.rangeCount) return;
    if (!ed.contains(sel.anchorNode)) return;
    lastRange.current = sel.getRangeAt(0).cloneRange();
    const next = readFormats();
    setFormats(prev => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
  }, [editorRef]);

  React.useEffect(() => {
    document.addEventListener("selectionchange", sync);
    return () => document.removeEventListener("selectionchange", sync);
  }, [sync]);

  const restore = React.useCallback(() => {
    const ed = editorRef.current;
    if (!ed) return;
    if (document.activeElement !== ed) {
      ed.focus();
      const range = lastRange.current;
      if (range) {
        const sel = window.getSelection();
        sel?.removeAllRanges();
        sel?.addRange(range);
      }
    }
  }, [editorRef]);

  const exec = React.useCallback((cmd: string, value?: string) => {
    if (readOnly) return;
    restore();
    document.execCommand(cmd, false, value);
    changeRef.current();
    sync();
  }, [readOnly, restore, sync, changeRef]);

  const selectedText = React.useCallback(() => {
    const sel = window.getSelection();
    return sel && sel.rangeCount ? sel.toString() : "";
  }, []);

  /**
   * Insert block markup at the caret.
   *
   * A block goes BETWEEN the editor's top-level children, never inside a
   * paragraph, so it lands beside the block the caret is in. An empty
   * paragraph at that spot is consumed, so inserting twice does not leave
   * blank lines stacking up.
   */
  const insertHTML = React.useCallback((html: string) => {
    if (readOnly) return;
    const ed = editorRef.current;
    if (!ed) return;

    const resolved = html === "@checklist" ? BLOCKS.check() : html;
    const tmp = document.createElement("div");
    tmp.innerHTML = resolved;
    const nodes = [...tmp.childNodes];

    let anchor = lastRange.current && ed.contains(lastRange.current.startContainer)
      ? (lastRange.current.startContainer as Node | null)
      : null;
    while (anchor && anchor.parentNode !== ed) anchor = anchor.parentNode;

    const anchorEl = anchor as HTMLElement | null;
    const emptyAnchor = !!anchorEl && anchorEl.tagName === "P" && !anchorEl.textContent?.trim();
    const ref = emptyAnchor ? anchorEl : (anchorEl?.nextSibling ?? null);

    nodes.forEach(n => ed.insertBefore(n, ref));
    if (emptyAnchor && anchorEl && anchorEl !== nodes[nodes.length - 1]) anchorEl.remove();

    afterRef.current();
    const first = nodes.find(n => n.nodeType === 1) as HTMLElement | undefined;
    if (first) first.scrollIntoView({ block: "center", behavior: "smooth" });
    changeRef.current();
  }, [readOnly, editorRef, changeRef, afterRef]);

  const insertCode = React.useCallback(() => {
    if (readOnly) return;
    restore();
    const text = selectedText().replace(/&/g, "&amp;").replace(/</g, "&lt;");
    // The zero-width space gives the caret somewhere outside the <code> to
    // land, so typing after it is not also code.
    document.execCommand("insertHTML", false, `<code>${text || "code"}</code>&#8203;`);
    changeRef.current();
  }, [readOnly, restore, selectedText, changeRef]);

  const insertLink = React.useCallback(() => {
    if (readOnly) return;
    const url = window.prompt("Link URL");
    if (!url) return;
    exec("createLink", /^https?:|^mailto:/.test(url) ? url : `https://${url}`);
  }, [readOnly, exec]);

  return {
    formats, exec, insertHTML, insertCode, insertLink, restore, selectedText, sync, lastRange,
  };
}
