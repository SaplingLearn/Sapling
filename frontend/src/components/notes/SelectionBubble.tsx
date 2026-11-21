"use client";
/**
 * The bubble that appears over a text selection: Ask Clov, Explain, Improve
 * Wording, and a highlighter.
 *
 * `onMouseDown` is swallowed on the bubble itself — pressing a button must
 * not collapse the selection it is about to act on.
 */
import React from "react";

import { Glyph } from "../library/primitives";

export interface SelectionBubbleProps {
  /** Where to sit, in the editor section's own coordinates. */
  x: number;
  y: number;
  onAsk: () => void;
  onExplain: () => void;
  onImprove: () => void;
  onHighlight: () => void;
}

export function SelectionBubble(props: SelectionBubbleProps) {
  const { x, y, onAsk, onExplain, onImprove, onHighlight } = props;

  const item: React.CSSProperties = {
    height: 34, padding: "0 12px", border: 0, borderRadius: 9, background: "transparent",
    color: "#FFFFFF", font: "inherit", fontSize: 14, fontWeight: 600, cursor: "pointer",
  };

  return (
    <div
      onMouseDown={e => e.preventDefault()}
      data-testid="notes-selection-bubble"
      style={{
        position: "absolute", left: x, top: y, transform: "translateX(-50%)", zIndex: 8,
        display: "flex", alignItems: "center", gap: 2, padding: 4, borderRadius: 12,
        background: "#1A1814", boxShadow: "0 10px 24px rgba(25,37,11,0.25)",
      }}
    >
      <button
        className="sapHoverOnDark"
        onClick={onAsk}
        style={{ ...item, display: "flex", alignItems: "center", gap: 7, padding: "0 12px 0 8px", fontWeight: 700 }}
      >
        <Glyph name="clov" size={16} fill="#A9D18E" />
        Ask Clov
      </button>
      <button className="sapHoverOnDark" onClick={onExplain} style={item}>Explain</button>
      <button className="sapHoverOnDark" onClick={onImprove} style={item}>Improve Wording</button>
      <span style={{ width: 1, height: 20, margin: "0 2px", background: "rgba(255,255,255,0.2)" }} />
      <button
        className="sapHoverOnDark"
        onClick={onHighlight}
        title="Highlight"
        aria-label="Highlight"
        style={{
          width: 34, height: 34, display: "grid", placeItems: "center", border: 0,
          borderRadius: 9, background: "transparent", cursor: "pointer",
        }}
      >
        <span style={{ width: 16, height: 16, borderRadius: 4, background: "#F6E7B0" }} />
      </button>
    </div>
  );
}
