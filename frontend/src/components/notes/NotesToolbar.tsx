"use client";
/**
 * The floating formatting toolbar: undo/redo, the text-style dropdown, the
 * inline marks, lists, alignment, the equation button and the Insert menu.
 *
 * It spans the document column with no cover behind it and no gap above, and
 * every size transitions on the same 380 ms curve as the Ask Clov panel — so
 * opening Clov visibly squeezes it rather than swapping it for a smaller one.
 */
import React from "react";

import { BLOCK_MENU, GRAPH_KINDS } from "@/lib/notes/blocks";
import {
  ALIGNMENTS, METRICS, SQUEEZE, currentAlignment, currentStyle, isSeparator,
  leadingTools, mainTools, styleLabel, TEXT_STYLES,
  type Formats, type Tool, type ToolOrSeparator,
} from "./toolbarModel";
import { MENU_IN, MENU_OUT, MENU_SURFACE } from "../library/primitives";

export type ToolbarMenu = "style" | "insert" | "align" | null;

export interface NotesToolbarProps {
  formats: Formats;
  clovOpen: boolean;
  /** Where the toolbar's left and right edges sit, measured by the page. */
  left: number;
  right: number;
  menu: ToolbarMenu;
  onMenu: (m: ToolbarMenu) => void;
  menuClosing: boolean;
  exec: (cmd: string, value?: string) => void;
  insertHTML: (html: string) => void;
  insertCode: () => void;
  insertLink: () => void;
  insertEquation: () => void;
  insertBlock: (html: string) => void;
  insertGraph: (kind: "fn" | "bar" | "line" | "scatter" | "pie") => void;
  setBlockStyle: (block: string) => void;
}

function ToolButton({ tool, metrics }: { tool: Tool; metrics: typeof METRICS.wide }) {
  return (
    <button
      className="sapHoverWarmer"
      onMouseDown={e => { e.preventDefault(); tool.run(); }}
      title={tool.tip}
      aria-label={tool.tip}
      aria-pressed={!!tool.on}
      style={{
        minWidth: metrics.button,
        height: metrics.button,
        padding: `0 ${metrics.padX}`,
        transition: `min-width ${SQUEEZE}, height ${SQUEEZE}, padding ${SQUEEZE}, background 120ms`,
        boxSizing: "border-box",
        display: "grid",
        placeItems: "center",
        border: 0,
        borderRadius: 8,
        background: tool.on ? "#DCE8CE" : "transparent",
        color: tool.on ? "#2F4417" : "#3F3B31",
        fontFamily: tool.font ?? "inherit",
        fontSize: 16,
        fontWeight: tool.weight ?? 600,
        fontStyle: tool.style ?? "normal",
        textDecoration: tool.decoration ?? "none",
        cursor: "pointer",
      }}
    >
      {tool.path ? (
        <svg
          width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor"
          strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
        >
          <path d={tool.path} />
        </svg>
      ) : (
        <span>{tool.label}</span>
      )}
    </button>
  );
}

function Separator({ margin }: { margin: string }) {
  return (
    <span style={{
      width: 1, height: 22, transition: `margin ${SQUEEZE}`,
      margin: `0 ${margin}`, background: "rgba(42,39,31,0.12)",
    }} />
  );
}

function renderTools(tools: ToolOrSeparator[], metrics: typeof METRICS.wide) {
  return tools.map((t, i) => (isSeparator(t)
    ? <Separator key={`sep-${i}`} margin={metrics.separator} />
    : <ToolButton key={t.key} tool={t} metrics={metrics} />));
}

export function NotesToolbar(props: NotesToolbarProps) {
  const {
    formats, clovOpen, left, right, menu, onMenu, menuClosing, exec, insertHTML,
    insertCode, insertLink, insertEquation, insertBlock, insertGraph, setBlockStyle,
  } = props;

  const m = clovOpen ? METRICS.narrow : METRICS.wide;
  const anim = menuClosing ? MENU_OUT : MENU_IN;
  const style = currentStyle(formats);
  const align = currentAlignment(formats);

  return (
    <div style={{
      animation: "sapFadeIn 220ms cubic-bezier(0.2, 0.7, 0.2, 1) 900ms both",
      position: "absolute",
      top: m.top,
      left,
      right,
      display: "flex",
      justifyContent: "center",
      zIndex: 11,
      pointerEvents: "none",
      transition: `top ${SQUEEZE}, left ${SQUEEZE}, right ${SQUEEZE}`,
    }}>
      <div
        role="toolbar"
        aria-label="Formatting"
        data-testid="notes-toolbar"
        style={{
          pointerEvents: "auto",
          display: "flex",
          alignItems: "center",
          gap: 2,
          padding: m.outerPad,
          transition: `padding ${SQUEEZE}`,
          background: "#FDFCF9",
          border: "1px solid rgba(42,39,31,0.10)",
          borderRadius: 14,
          boxShadow: "0 4px 16px rgba(25,37,11,0.07)",
        }}
      >
        {renderTools(leadingTools({ exec }), m)}
        <Separator margin={m.separator} />

        <div style={{ position: "relative" }}>
          <button
            className="sapHoverWarmer"
            onMouseDown={e => { e.preventDefault(); onMenu(menu === "style" ? null : "style"); }}
            aria-haspopup="listbox"
            aria-expanded={menu === "style"}
            title="Text style"
            style={{
              display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10,
              width: m.styleWidth, height: m.button,
              transition: `width ${SQUEEZE}, height ${SQUEEZE}, background 120ms`,
              padding: "0 10px 0 12px", border: 0, borderRadius: 9,
              background: menu === "style" ? "#F0ECE3" : "transparent",
              color: "#1A1814", font: "inherit", fontSize: 15, fontWeight: 500, cursor: "pointer",
            }}
          >
            <span style={{ whiteSpace: "nowrap" }}>{styleLabel(style, clovOpen)}</span>
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
              <path
                d="M3 4.5L6 7.5 9 4.5" fill="none" stroke="#6F6857" strokeWidth="1.5"
                strokeLinecap="round" strokeLinejoin="round"
              />
            </svg>
          </button>
          {menu === "style" && (
            <div role="listbox" style={{
              position: "absolute", top: 46, left: 0, width: 220, zIndex: 10,
              transformOrigin: "top left", animation: anim, ...MENU_SURFACE,
            }}>
              {TEXT_STYLES.map(s => (
                <button
                  key={s.tag}
                  role="option"
                  aria-selected={s === style}
                  className="sapHoverMenu"
                  onMouseDown={e => { e.preventDefault(); setBlockStyle(s.block); onMenu(null); }}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    gap: 10, padding: "8px 10px", border: 0, borderRadius: 8,
                    background: s === style ? "#EBF0E1" : "transparent", color: "#1A1814",
                    fontFamily: s.font, fontSize: s.size, fontWeight: s.weight,
                    textAlign: "left", cursor: "pointer",
                  }}
                >
                  <span>{s.label}</span>
                  {s === style && (
                    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                      <path
                        d="M3 7.5l2.5 2.5L11 4.5" fill="none" stroke="#445D22" strokeWidth="1.8"
                        strokeLinecap="round" strokeLinejoin="round"
                      />
                    </svg>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        <Separator margin={m.separator} />
        {renderTools(
          mainTools({ formats, exec, insertHTML, insertCode, insertLink, clovOpen }), m,
        )}

        {clovOpen && (
          <div style={{ position: "relative" }}>
            <button
              className="sapHoverWarmer"
              onMouseDown={e => { e.preventDefault(); onMenu(menu === "align" ? null : "align"); }}
              title="Align"
              aria-label="Align"
              aria-expanded={menu === "align"}
              style={{
                height: m.button, display: "flex", alignItems: "center", gap: 1,
                padding: "0 3px 0 5px", border: 0, borderRadius: 8,
                background: menu === "align" ? "#F0ECE3" : "transparent",
                color: "#3F3B31", cursor: "pointer",
                transition: `width ${SQUEEZE}, min-width ${SQUEEZE}, `
                  + `height ${SQUEEZE}, padding ${SQUEEZE}, background 120ms`,
              }}
            >
              <svg
                width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor"
                strokeWidth="1.5" strokeLinecap="round" aria-hidden="true"
              >
                <path d={align.path} />
              </svg>
              <svg width="10" height="10" viewBox="0 0 12 12" aria-hidden="true">
                <path
                  d="M3 4.5L6 7.5 9 4.5" fill="none" stroke="#6F6857" strokeWidth="1.5"
                  strokeLinecap="round" strokeLinejoin="round"
                />
              </svg>
            </button>
            {menu === "align" && (
              <div role="menu" style={{
                position: "absolute", top: 40, left: "50%", marginLeft: -58, zIndex: 12,
                padding: 4, display: "flex", gap: 2, background: "#FDFCF9",
                border: "1px solid rgba(42,39,31,0.14)", borderRadius: 10,
                boxShadow: "0 14px 36px rgba(25,37,11,0.16)",
                transformOrigin: "top center", animation: anim,
              }}>
                {ALIGNMENTS.map(a => (
                  <button
                    key={a.cmd}
                    role="menuitem"
                    className="sapHoverWarmer"
                    onMouseDown={e => { e.preventDefault(); exec(a.cmd); onMenu(null); }}
                    title={a.tip}
                    aria-label={a.tip}
                    style={{
                      width: 34, height: 32, display: "grid", placeItems: "center", border: 0,
                      borderRadius: 7, background: a === align ? "#DCE8CE" : "transparent",
                      color: "#3F3B31", cursor: "pointer",
                    }}
                  >
                    <svg
                      width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor"
                      strokeWidth="1.5" strokeLinecap="round" aria-hidden="true"
                    >
                      <path d={a.path} />
                    </svg>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <Separator margin={m.separator} />

        <button
          className="sapHoverWarmer"
          onMouseDown={e => { e.preventDefault(); insertEquation(); }}
          title="Equation"
          aria-label="Insert equation"
          data-testid="notes-insert-equation"
          style={{
            minWidth: m.button, height: m.button, padding: `0 ${m.padX}`, border: 0,
            borderRadius: 8, background: "transparent", color: "#3F3B31",
            fontFamily: "var(--font-serif)", fontStyle: "italic", fontSize: 16,
            cursor: "pointer",
            transition: `min-width ${SQUEEZE}, height ${SQUEEZE}, padding ${SQUEEZE}, background 120ms`,
          }}
        >√x</button>

        <div style={{ position: "relative" }}>
          <button
            className="sapHoverForestLight"
            onMouseDown={e => { e.preventDefault(); onMenu(menu === "insert" ? null : "insert"); }}
            aria-expanded={menu === "insert"}
            aria-label="Insert"
            data-testid="notes-insert"
            style={{
              display: "flex", alignItems: "center", gap: 6, height: m.button, marginLeft: 4,
              padding: `0 ${m.insertPadRight} 0 ${m.insertPadLeft}`, border: 0, borderRadius: 9,
              background: "#445D22", color: "#FFFFFF", font: "inherit", fontSize: 14,
              fontWeight: 700, cursor: "pointer",
              transition: `padding ${SQUEEZE}, height ${SQUEEZE}, background 120ms`,
            }}
          >
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
              <path d="M7 2v10M2 7h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            {!clovOpen && <span>Insert</span>}
          </button>

          {menu === "insert" && (
            <div role="menu" style={{
              position: "absolute", top: 46, right: 0, width: 330, padding: 6,
              display: "flex", flexDirection: "column", background: "#FDFCF9",
              border: "1px solid rgba(42,39,31,0.14)", borderRadius: 14,
              boxShadow: "0 14px 36px rgba(25,37,11,0.16)",
              transformOrigin: "top right", animation: anim,
            }}>
              <div style={{
                display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 2,
                padding: "2px 0 6px", marginBottom: 4,
                borderBottom: "1px solid rgba(42,39,31,0.08)",
              }}>
                {GRAPH_KINDS.map(g => (
                  <button
                    key={g.key}
                    role="menuitem"
                    className="sapHoverMenu"
                    onMouseDown={e => { e.preventDefault(); insertGraph(g.key); onMenu(null); }}
                    style={{
                      display: "flex", flexDirection: "column", alignItems: "center", gap: 6,
                      padding: "8px 0 6px", border: 0, borderRadius: 10, background: "transparent",
                      font: "inherit", fontSize: 12, fontWeight: 600, color: "#3F3B31",
                      cursor: "pointer",
                    }}
                  >
                    <span style={{
                      width: 34, height: 34, borderRadius: 9, background: "#EBF0E1",
                      color: "#2F4417", display: "grid", placeItems: "center",
                    }}>
                      <svg
                        width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor"
                        strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <path d={g.icon} />
                      </svg>
                    </span>
                    {g.label}
                  </button>
                ))}
              </div>

              {BLOCK_MENU.map(b => (
                <button
                  key={b.label}
                  role="menuitem"
                  className="sapHoverMenu"
                  onMouseDown={e => { e.preventDefault(); insertBlock(b.html()); onMenu(null); }}
                  style={{
                    display: "flex", alignItems: "center", gap: 12, padding: "8px 10px",
                    border: 0, borderRadius: 10, background: "transparent", font: "inherit",
                    textAlign: "left", cursor: "pointer",
                  }}
                >
                  <span style={{
                    width: 34, height: 34, flexShrink: 0, borderRadius: 9, background: b.bg,
                    color: b.fg, display: "grid", placeItems: "center",
                    fontFamily: "var(--font-serif)", fontSize: 15, fontWeight: 700,
                  }}>{b.glyph}</span>
                  <span style={{ display: "flex", flexDirection: "column" }}>
                    <span style={{ fontSize: 15, fontWeight: 700, color: "#1A1814" }}>{b.label}</span>
                    <span style={{ fontSize: 13, color: "#6F6857" }}>{b.desc}</span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
