"use client";
/**
 * The symbol palette, offered only for an equation that is still empty.
 *
 * Structures come first (fraction, power, root, the big operators), then the
 * loose symbols. Picking one inserts its template and drops the caret into
 * its first box; after that the equation is edited by clicking its parts, so
 * the palette gets out of the way.
 */
import React from "react";

import { STRUCTURE_COUNT, SYMBOLS, SYMBOL_PREVIEW } from "@/lib/notes/mathSlots";

export interface MathPaletteProps {
  left: number;
  top: number;
  onInsert: (tpl: string) => void;
  onDone: () => void;
  /** Renders a button's preview with KaTeX; empty until KaTeX has loaded. */
  preview: (tex: string) => string;
}

function Grid({
  items, structures, onInsert, preview,
}: {
  items: [string, string][];
  structures: boolean;
  onInsert: (tpl: string) => void;
  preview: (tex: string) => string;
}) {
  return (
    <div className={`mq-syms${structures ? " st" : ""}`}>
      {items.map(([label, tpl]) => {
        const html = preview(SYMBOL_PREVIEW[tpl] ?? tpl.trim());
        return (
          <button
            key={tpl}
            type="button"
            title={tpl.trim()}
            onMouseDown={e => { e.preventDefault(); onInsert(tpl); }}
            // KaTeX gives us a rendered fragment; the plain label stands in
            // until it has loaded, so the palette is never blank.
            {...(html
              ? { dangerouslySetInnerHTML: { __html: html } }
              : { children: label })}
          />
        );
      })}
    </div>
  );
}

export function MathPalette({ left, top, onInsert, onDone, preview }: MathPaletteProps) {
  return (
    <div
      className="mq-pop"
      contentEditable={false}
      data-testid="notes-math-palette"
      style={{ left, top }}
    >
      <div className="mq-lbl">Structures</div>
      <Grid
        items={SYMBOLS.slice(0, STRUCTURE_COUNT)}
        structures
        onInsert={onInsert}
        preview={preview}
      />
      <div className="mq-lbl">Symbols</div>
      <Grid
        items={SYMBOLS.slice(STRUCTURE_COUNT)}
        structures={false}
        onInsert={onInsert}
        preview={preview}
      />
      <div className="mq-foot">
        <span className="mq-hint">
          Pick a symbol, then type into its boxes · Tab next box · Enter done
        </span>
        <button
          type="button"
          className="mq-done"
          onMouseDown={e => { e.preventDefault(); onDone(); }}
        >Done</button>
      </div>
    </div>
  );
}
