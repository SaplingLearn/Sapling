"use client";
import React from "react";
import { Icon } from "../Icon";
import { INHERIT_FONT } from "@/lib/inheritFont";

const FOLDER_D =
  "M3 6.5A1.5 1.5 0 0 1 4.5 5h4.6l2 2.2h8.4A1.5 1.5 0 0 1 21 8.7v9.8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z";

export function FolderIcon({ size = 15, strokeWidth = 2 }: { size?: number; strokeWidth?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0.5 24 24" fill="#B8873F" stroke="#B8873F"
      strokeWidth={strokeWidth} strokeLinejoin="round" aria-hidden="true" style={{ flexShrink: 0 }}>
      <path d={FOLDER_D} />
    </svg>
  );
}

/** A design-system icon tinted through `color` (Icon paints with currentColor). */
export function Tinted({ name, size, color }: { name: string; size: number; color: string }) {
  return (
    <span aria-hidden="true" style={{ display: "inline-flex", color, flexShrink: 0 }}>
      <Icon name={name} size={size} />
    </span>
  );
}

export function CheckBox({
  checked, label, onClick, size = 20, card = false,
}: { checked: boolean; label: string; onClick: (e: React.MouseEvent) => void; size?: number; card?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={checked}
      style={{
        width: size, height: size, borderRadius: card ? 6 : 5,
        border: `1.5px solid ${checked ? "#445D22" : "rgba(42,39,31,0.28)"}`,
        background: checked ? "#445D22" : card ? "rgba(253,252,249,0.92)" : "#FDFCF9",
        color: "#FFFFFF", display: "grid", placeItems: "center", padding: 0, cursor: "pointer",
        boxSizing: "border-box",
      }}
    >
      <span style={{ opacity: checked ? 1 : 0, display: "inline-flex" }}><Icon name="check" size={11} /></span>
    </button>
  );
}

export function CourseDot({ color, size = 8 }: { color: string | null; size?: number }) {
  return (
    <span style={{
      width: size, height: size, borderRadius: "50%", flexShrink: 0, boxSizing: "border-box",
      background: color || "transparent", border: color ? 0 : "1.5px dashed #8A8372",
    }} />
  );
}

/** Rendered stand-in for a document's first page (no page image is stored). */
export function PageCard({
  h, lines, accent, compact = false,
}: { h: string; lines: string[]; accent?: string; compact?: boolean }) {
  if (compact) {
    return (
      <div style={{ height: 176, background: "#EFEBE2", padding: "16px 22px 0", boxSizing: "border-box", overflow: "hidden" }}>
        <div style={{
          height: 220, background: "#FFFFFF", borderRadius: "4px 4px 0 0", boxShadow: "0 1px 3px rgba(25,37,11,0.12)",
          padding: "16px 16px 0", boxSizing: "border-box", display: "flex", flexDirection: "column", gap: 6,
        }}>
          <span style={{ height: 4, width: 28, borderRadius: 2, background: accent }} />
          <span style={{ fontFamily: "var(--font-serif)", fontSize: 17, fontWeight: 600, lineHeight: 1.2 }}>{h}</span>
          {lines.map((ln, i) => (
            <span key={i} style={{ fontSize: 10.5, lineHeight: 1.45, color: "#3F3B31" }}>{ln}</span>
          ))}
          <span style={{ height: 5, width: "92%", borderRadius: 3, background: "#EEEAE1", flexShrink: 0 }} />
          <span style={{ height: 5, width: "70%", borderRadius: 3, background: "#EEEAE1", flexShrink: 0 }} />
        </div>
      </div>
    );
  }
  return (
    <div style={{
      marginTop: 18, background: "#FFFFFF", borderRadius: 6, boxShadow: "0 1px 2px rgba(25,37,11,0.08)",
      padding: "18px 20px 20px", display: "flex", flexDirection: "column", gap: 8,
    }}>
      <span style={{ fontFamily: "var(--font-serif)", fontSize: 24, fontWeight: 600, lineHeight: 1.15 }}>{h}</span>
      {lines.map((ln, i) => (
        <span key={i} style={{ fontSize: 15, color: "#3F3B31", lineHeight: 1.45 }}>{ln}</span>
      ))}
    </div>
  );
}

export const menuPanel: React.CSSProperties = {
  background: "#FDFCF9", border: "1px solid rgba(42,39,31,0.14)", borderRadius: 12,
  boxShadow: "0 14px 36px rgba(25,37,11,0.16)", padding: 6, display: "flex", flexDirection: "column", gap: 1,
};

export const menuItemStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 10, padding: "9px 10px", border: 0, borderRadius: 8,
  background: "transparent", ...INHERIT_FONT, fontSize: 14, fontWeight: 600, textAlign: "left", cursor: "pointer",
  color: "#1A1814",
};

export const menuHeading: React.CSSProperties = {
  padding: "8px 10px 4px", fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.12em",
  textTransform: "uppercase", color: "#6F6857",
};

export const renameInput: React.CSSProperties = {
  width: "100%", boxSizing: "border-box", height: 30, padding: "0 8px", border: "1.5px solid #597536",
  borderRadius: 7, background: "#FFFFFF", ...INHERIT_FONT, fontSize: 16, fontWeight: 600, color: "#1A1814", outline: "none",
};
