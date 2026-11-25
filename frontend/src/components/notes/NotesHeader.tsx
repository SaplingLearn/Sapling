"use client";
/**
 * The Notes page's top row: back to the Library, the breadcrumb, the save
 * state, Share, Download, Regenerate, and Finalize / Edit.
 *
 * Its right edge moves with the Ask Clov panel so it is never slid under it,
 * and Share and Download drop their labels when the panel takes the room.
 */
import React from "react";

import { MENU_IN, MENU_OUT, MENU_SURFACE } from "../library/primitives";
import { METRICS, SQUEEZE } from "./toolbarModel";

export type HeaderMenu = "download" | null;

export interface NotesHeaderProps {
  courseLabel: string;
  courseColor: string;
  docTitle: string;
  /** "Saved" / "Saving…" / "Not saved". */
  saveState: string;
  clovOpen: boolean;
  final: boolean;
  onBack: () => void;
  onShare: () => void;
  onToggleFinal: () => void;
  onRegenerate: () => void;
  regenerating: boolean;
  menu: HeaderMenu;
  onMenu: (m: HeaderMenu) => void;
  menuClosing: boolean;
  downloads: { label: string; ext: string; run: () => void }[];
  /** Measured by the page so the toolbar can sit between the two groups. */
  leftRef: React.RefObject<HTMLDivElement | null>;
  rightRef: React.RefObject<HTMLDivElement | null>;
}

export function NotesHeader(props: NotesHeaderProps) {
  const {
    courseLabel, courseColor, docTitle, saveState, clovOpen, final, onBack, onShare,
    onToggleFinal, onRegenerate, regenerating, menu, onMenu, menuClosing, downloads,
    leftRef, rightRef,
  } = props;

  const m = clovOpen ? METRICS.narrow : METRICS.wide;
  // The breadcrumb and the save line sit over the document, so they carry a
  // paper-coloured glow rather than a panel behind them.
  const glow = "0 0 2px #FAF8F3, 0 0 8px #FAF8F3, 0 0 14px #FAF8F3, 0 0 22px #FAF8F3";

  const iconButton: React.CSSProperties = {
    minWidth: 36, justifyContent: "center", height: 36, boxSizing: "border-box",
    display: "inline-flex", alignItems: "center", gap: 7,
    padding: `0 ${m.headerButtonPad}`,
    transition: `padding ${SQUEEZE}, background 120ms`,
    borderRadius: 10, font: "inherit", fontSize: 14, fontWeight: 700, cursor: "pointer",
    border: "1px solid rgba(42,39,31,0.14)", background: "#FFFFFF", color: "#3F3B31",
  };

  return (
    <header style={{
      animation: "sapFadeIn 260ms cubic-bezier(0.2, 0.7, 0.2, 1) 820ms both",
      position: "absolute", top: 0, left: 0, right: m.headerRight, zIndex: 10,
      transition: `right ${SQUEEZE}`,
      height: 76, flexShrink: 0, display: "flex", alignItems: "center", gap: 14,
      padding: "0 28px 0 32px", background: "transparent",
    }}>
      <button
        onClick={onBack}
        title="Back to Library"
        aria-label="Back to Library"
        data-testid="notes-back"
        className="sapHoverMint"
        style={{
          width: 34, height: 34, flexShrink: 0, margin: "0 -10px 0 -8px", display: "grid",
          placeItems: "center", border: 0, borderRadius: 9, background: "transparent",
          color: "#445D22", cursor: "pointer",
        }}
      >
        <svg
          width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor"
          strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
        >
          <path d="M11 4L6 9l5 5" />
        </svg>
      </button>

      <div ref={leftRef} style={{
        position: "relative", display: "flex", alignItems: "center", minWidth: 0, flex: "0 1 auto",
      }}>
        <nav aria-label="Breadcrumb" style={{
          flex: "0 1 auto", display: "flex", alignItems: "center", gap: 10, lineHeight: 1,
          minWidth: 0, maxWidth: m.navMax, height: 28, textShadow: glow,
          fontSize: 15, color: "#6F6857", whiteSpace: "nowrap",
        }}>
          <span style={{
            flexShrink: 0, display: "inline-flex", alignItems: "center", gap: 8, lineHeight: 1,
          }}>
            <span style={{
              display: "block", flexShrink: 0, width: 9, height: 9, borderRadius: "50%",
              background: courseColor,
            }} />
            <span>{courseLabel}</span>
          </span>
          <span style={{ flexShrink: 0 }}>/</span>
          <span title={docTitle} style={{
            minWidth: 0, color: "#1A1814", fontWeight: 700, overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>{docTitle}</span>
        </nav>
        <span data-testid="notes-save-state" style={{
          position: "absolute", left: 0, top: "calc(100% + 4px)", display: "inline-flex",
          alignItems: "center", gap: 6, whiteSpace: "nowrap", fontSize: 14,
          color: saveState === "Not saved" ? "#A8443F" : "#6F6857",
          textShadow: "0 0 2px #FAF8F3, 0 0 8px #FAF8F3, 0 0 14px #FAF8F3",
        }}>
          <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
            <path
              d="M3.5 8.5l3 3 6-7" fill="none"
              stroke={saveState === "Not saved" ? "#A8443F" : "#597536"}
              strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
            />
          </svg>
          {saveState}
        </span>
      </div>

      <div style={{ flex: 1 }} />

      <div ref={rightRef} style={{
        flexShrink: 0, display: "flex", alignItems: "center", gap: 6, marginLeft: 4,
      }}>
        {!final && (
          <button
            onClick={onRegenerate}
            disabled={regenerating}
            title="Rebuild these notes from the document"
            aria-label="Regenerate notes"
            data-testid="notes-regenerate"
            className="sapHoverWarm"
            style={{ ...iconButton, opacity: regenerating ? 0.6 : 1 }}
          >
            <svg
              width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor"
              strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
            >
              <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9" />
              <path d="M13.5 2.5V5H11" />
            </svg>
            {!clovOpen && <span>{regenerating ? "Rebuilding…" : "Regenerate"}</span>}
          </button>
        )}

        <button
          onClick={onShare}
          title="Share"
          aria-label="Share"
          data-testid="notes-share"
          className="sapHoverWarm"
          style={iconButton}
        >
          <svg
            width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor"
            strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
          >
            <path d="M8 10V2.5M5 5.5l3-3 3 3M3 9v3.5h10V9" />
          </svg>
          {!clovOpen && <span>Share</span>}
        </button>

        <div style={{ position: "relative" }}>
          <button
            onClick={() => onMenu(menu === "download" ? null : "download")}
            title="Download"
            aria-label="Download"
            aria-expanded={menu === "download"}
            data-testid="notes-download"
            className="sapHoverWarm"
            style={iconButton}
          >
            <svg
              width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor"
              strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
            >
              <path d="M8 2.5V10M5 7l3 3 3-3M3 13.5h10" />
            </svg>
            {!clovOpen && <span>Download</span>}
          </button>
          {menu === "download" && (
            <div role="menu" style={{
              position: "absolute", top: 46, right: 0, zIndex: 12, width: 220,
              transformOrigin: "top right", animation: menuClosing ? MENU_OUT : MENU_IN,
              ...MENU_SURFACE,
            }}>
              {downloads.map(d => (
                <button
                  key={d.ext}
                  role="menuitem"
                  className="sapHoverMenu"
                  onClick={() => { d.run(); onMenu(null); }}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "9px 10px", border: 0, borderRadius: 8, background: "transparent",
                    font: "inherit", fontSize: 14, fontWeight: 600, color: "#1A1814",
                    textAlign: "left", cursor: "pointer",
                  }}
                >
                  <span>{d.label}</span>
                  <span style={{
                    fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 400,
                    color: "#8A8372",
                  }}>{d.ext}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <button
          onClick={onToggleFinal}
          data-testid="notes-finalize"
          className={final ? "sapHoverTintStrong" : "sapHoverForestLight"}
          style={{
            height: 36, boxSizing: "border-box", display: "inline-flex", alignItems: "center",
            gap: 7, padding: "0 14px", borderRadius: 10, font: "inherit", fontSize: 14,
            fontWeight: 700, cursor: "pointer",
            border: final ? "1px solid rgba(42,39,31,0.14)" : "1px solid #445D22",
            background: final ? "#EBF0E1" : "#445D22",
            color: final ? "#2F4417" : "#FFFFFF",
          }}
        >
          {final ? (
            <>
              <svg
                width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
              >
                <path d="M10.5 2.5l3 3-8 8H2.5v-3z" />
              </svg>
              Edit
            </>
          ) : (
            <>
              <svg
                width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
              >
                <path d="M3.5 8.5l3 3 6-7" />
              </svg>
              Finalize
            </>
          )}
        </button>
      </div>
    </header>
  );
}
