"use client";

import React from "react";
import { CANDIDATES, DEFAULT_SELECTION, ROLES, type FontRole } from "@/lib/fontLab/candidates";
import {
  FONT_LAB_EVENT,
  FONT_LAB_STORAGE_KEY,
  readFontLabSelection,
  type FontLabSelection,
} from "@/lib/fontLab/navOverride";

const DOCK_OPEN_KEY = "sapling_font_lab_dock_open";

function writeSelection(selection: FontLabSelection) {
  try {
    window.localStorage.setItem(FONT_LAB_STORAGE_KEY, JSON.stringify(selection));
    window.dispatchEvent(new Event(FONT_LAB_EVENT));
  } catch {
    // Best-effort, same as the lab page itself.
  }
}

function step(role: FontRole, current: string, dir: 1 | -1): string {
  const list = CANDIDATES[role];
  const i = list.findIndex((c) => c.family === current);
  const next = (i < 0 ? 0 : i + dir + list.length) % list.length;
  return list[next].family;
}

/**
 * A floating dock, mounted on every shell page in development only, that
 * cycles the /font-lab selection in place — so a combination can be judged
 * by looking straight at the live SideNav, without alt-tabbing to the lab's
 * separate replica page. Reads/writes the exact same localStorage key +
 * event that `/font-lab` and `useNavFontOverride` already use, so this is
 * just a second, in-context editor for the same state, not a parallel system.
 *
 * Dev-only: the `NODE_ENV` check below is a literal the production bundler
 * dead-code-eliminates, so this never ships to a real user's dashboard.
 */
export function FontLabDock() {
  const [selection, setSelectionState] = React.useState<FontLabSelection>(DEFAULT_SELECTION);
  const [open, setOpen] = React.useState(false);
  const [hydrated, setHydrated] = React.useState(false);

  React.useEffect(() => {
    setSelectionState({ ...DEFAULT_SELECTION, ...readFontLabSelection() });
    try {
      setOpen(window.localStorage.getItem(DOCK_OPEN_KEY) === "1");
    } catch {}
    setHydrated(true);
  }, []);

  React.useEffect(() => {
    function sync() {
      setSelectionState({ ...DEFAULT_SELECTION, ...readFontLabSelection() });
    }
    window.addEventListener("storage", sync);
    window.addEventListener(FONT_LAB_EVENT, sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener(FONT_LAB_EVENT, sync);
    };
  }, []);

  function toggleOpen() {
    setOpen((o) => {
      const next = !o;
      try {
        window.localStorage.setItem(DOCK_OPEN_KEY, next ? "1" : "0");
      } catch {}
      return next;
    });
  }

  function cycle(role: FontRole, dir: 1 | -1) {
    const next = { ...selection, [role]: step(role, selection[role], dir) };
    setSelectionState(next);
    writeSelection(next);
  }

  function reset() {
    setSelectionState(DEFAULT_SELECTION);
    writeSelection(DEFAULT_SELECTION);
  }

  if (process.env.NODE_ENV === "production") return null;
  if (!hydrated) return null;

  if (!open) {
    return (
      <button
        type="button"
        onClick={toggleOpen}
        aria-label="Open Font Lab dock"
        title="Font Lab"
        style={{
          position: "fixed",
          // Bottom-RIGHT, not left: the sidebar owns the entire left edge —
          // its own collapse button, Settings, and avatar footer all live
          // there — and a fixed left-16/bottom-16 dock sat directly on top
          // of them. The dock's "Full lab" link was literally intercepting
          // clicks meant for the real Collapse button.
          right: 16,
          bottom: 16,
          zIndex: 9999,
          width: 40,
          height: 40,
          borderRadius: "50%",
          border: "1px solid var(--border)",
          background: "var(--bg-subtle)",
          color: "var(--brand-forest)",
          fontFamily: "var(--font-display)",
          fontWeight: 700,
          fontSize: 15,
          boxShadow: "0 2px 10px rgba(0,0,0,0.18)",
          cursor: "pointer",
        }}
      >
        Aa
      </button>
    );
  }

  return (
    <div
      style={{
        position: "fixed",
        right: 16,
        bottom: 16,
        zIndex: 9999,
        width: 300,
        borderRadius: "var(--r-sm)",
        border: "1px solid var(--border)",
        background: "var(--bg)",
        boxShadow: "0 8px 28px rgba(0,0,0,0.28)",
        padding: 12,
        fontFamily: "var(--font-sans)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: "0.04em", color: "var(--text)" }}>
          FONT LAB — live on this page
        </span>
        <button
          type="button"
          onClick={toggleOpen}
          aria-label="Close Font Lab dock"
          style={{ fontSize: 16, lineHeight: 1, color: "var(--text-dim)", background: "none", cursor: "pointer" }}
        >
          ×
        </button>
      </div>

      {ROLES.map((role) => (
        <div
          key={role.id}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 6,
            padding: "6px 0",
            borderTop: "1px solid var(--border)",
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              {role.label}
            </div>
            <div
              style={{
                fontSize: 12.5,
                fontWeight: 600,
                color: "var(--text)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={selection[role.id]}
            >
              {selection[role.id]}
            </div>
          </div>
          <div style={{ display: "flex", gap: 2, flexShrink: 0 }}>
            <button type="button" onClick={() => cycle(role.id, -1)} aria-label={`Previous ${role.label} font`} style={dockBtn}>
              ‹
            </button>
            <button type="button" onClick={() => cycle(role.id, 1)} aria-label={`Next ${role.label} font`} style={dockBtn}>
              ›
            </button>
          </div>
        </div>
      ))}

      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button type="button" onClick={reset} style={{ ...dockBtn, flex: 1, padding: "6px 8px", fontSize: 11.5 }}>
          Reset to shipped
        </button>
        <a
          href="/font-lab"
          style={{
            ...dockBtn,
            flex: 1,
            padding: "6px 8px",
            fontSize: 11.5,
            textAlign: "center",
            textDecoration: "none",
            display: "inline-block",
          }}
        >
          Full lab →
        </a>
      </div>
    </div>
  );
}

const dockBtn: React.CSSProperties = {
  border: "1px solid var(--border)",
  background: "var(--bg-subtle)",
  color: "var(--text)",
  borderRadius: "var(--r-xs)",
  width: 26,
  height: 26,
  fontSize: 14,
  cursor: "pointer",
};
