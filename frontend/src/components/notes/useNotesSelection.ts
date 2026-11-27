"use client";
/**
 * The selection bubble's state: where it sits, and what its four buttons do
 * to the passage that is selected.
 *
 * The range is captured when the bubble appears, not when a button is
 * pressed: by then the click may have collapsed it, and "Improve Wording"
 * needs to put the rewrite back over exactly the words it was given.
 */
import React from "react";

export interface NotesSelection {
  bubble: { x: number; y: number } | null;
  /** Called on mouse-up / key-up in the editor. */
  show: () => void;
  hide: () => void;
  ask: () => void;
  explain: () => void;
  improve: () => void;
  highlight: () => void;
}

export interface NotesSelectionInput {
  editorRef: React.RefObject<HTMLElement | null>;
  /** The bubble is positioned inside this, so it scrolls with the notes. */
  sectionRef: React.RefObject<HTMLElement | null>;
  enabled: boolean;
  onAsk: (text: string) => void;
  onExplain: (text: string) => void;
  onImprove: (text: string, range: Range) => void;
  onHighlight: (range: Range) => void;
}

/** Shorter than this is a stray click, not a passage. */
const MIN_CHARS = 2;

export function useNotesSelection(input: NotesSelectionInput): NotesSelection {
  const { editorRef, sectionRef, enabled, onAsk, onExplain, onImprove, onHighlight } = input;
  const [bubble, setBubble] = React.useState<{ x: number; y: number } | null>(null);
  const text = React.useRef("");
  const range = React.useRef<Range | null>(null);

  const hide = React.useCallback(() => setBubble(null), []);

  const show = React.useCallback(() => {
    if (!enabled) return;
    // The selection is not final until the event loop turns over.
    setTimeout(() => {
      const sel = window.getSelection();
      const ed = editorRef.current;
      const section = sectionRef.current;
      if (!sel || sel.isCollapsed || !sel.rangeCount || !ed || !section) { setBubble(null); return; }
      if (!ed.contains(sel.anchorNode)) { setBubble(null); return; }

      const selected = sel.toString().trim();
      if (selected.length < MIN_CHARS) { setBubble(null); return; }

      const r = sel.getRangeAt(0).getBoundingClientRect();
      const box = section.getBoundingClientRect();
      // Clamped so the bubble never hangs off either edge of the column.
      setBubble({
        x: Math.min(Math.max(r.left + r.width / 2 - box.left, 240), box.width - 240),
        y: Math.max(r.top - box.top - 52, 70),
      });
      text.current = selected;
      range.current = sel.getRangeAt(0).cloneRange();
    }, 0);
  }, [enabled, editorRef, sectionRef]);

  React.useEffect(() => {
    // A collapsed selection means the bubble has nothing to act on.
    const onChange = () => {
      const sel = window.getSelection();
      if (sel?.isCollapsed) setBubble(null);
    };
    document.addEventListener("selectionchange", onChange);
    return () => document.removeEventListener("selectionchange", onChange);
  }, []);

  const act = (fn: (t: string, r: Range) => void) => () => {
    const r = range.current;
    if (!r) return;
    fn(text.current, r);
    setBubble(null);
  };

  return {
    bubble,
    show,
    hide,
    ask: act(t => onAsk(t)),
    explain: act(t => onExplain(t)),
    improve: act((t, r) => onImprove(t, r)),
    highlight: act((_t, r) => onHighlight(r)),
  };
}
