"use client";
/**
 * Panel view: the same folders and documents as the list, as cards with a
 * miniature of the document's first page.
 */
import React from "react";

import type { DocFolder, Document as Doc } from "@/lib/types";
import {
  CheckBox, DotsIcon, FolderIcon, FONT_MONO, FONT_SERIF,
} from "./primitives";
import { RenameInput } from "./LibraryList";
import { pagePreview, type RowView } from "./rowModel";

export const PANEL_GRID: React.CSSProperties = {
  paddingTop: 16,
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))",
  gap: 24,
};

export interface FolderCardProps {
  folder: DocFolder;
  count: number;
  selected: boolean;
  dragOver: boolean;
  editing: boolean;
  draft: string;
  onDraft: (v: string) => void;
  onCommit: () => void;
  onCancel: () => void;
  onSelect: () => void;
  onOpen: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
}

export function FolderCard(props: FolderCardProps) {
  const {
    folder, count, selected, dragOver, editing, draft, onDraft, onCommit, onCancel,
    onSelect, onOpen, onDragOver, onDragLeave, onDrop,
  } = props;
  return (
    <div
      role="button"
      tabIndex={0}
      data-testid={`library-folder-${folder.id}`}
      aria-pressed={selected}
      onClick={onSelect}
      onDoubleClick={onOpen}
      onKeyDown={e => { if (e.key === "Enter") onOpen(); }}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      style={{
        display: "flex", flexDirection: "column", borderRadius: 14, background: "#FDFCF9",
        border: `1px solid ${dragOver || selected ? "#597536" : "rgba(42,39,31,0.12)"}`,
        boxShadow: "0 1px 2px rgba(25,37,11,0.04)", overflow: "hidden", cursor: "pointer",
      }}
    >
      <div style={{
        height: 176, background: dragOver ? "#DCE8CE" : "#EFEBE2",
        display: "grid", placeItems: "center",
      }}>
        <FolderIcon size={84} strokeWidth={1.6} />
      </div>
      <div style={{
        padding: "12px 14px 14px", display: "flex", flexDirection: "column", gap: 4,
        borderTop: "1px solid rgba(42,39,31,0.10)",
      }}>
        {editing && (
          <RenameInput
            value={draft} onChange={onDraft} onCommit={onCommit} onCancel={onCancel} fontSize={15}
          />
        )}
        <div style={{
          fontSize: 15, fontWeight: 600, lineHeight: 1.3, display: editing ? "none" : "block",
        }}>{folder.name}</div>
        <div style={{ fontSize: 13, color: "#6F6857" }}>
          Folder · {count} {count === 1 ? "document" : "documents"}
        </div>
      </div>
    </div>
  );
}

export interface DocCardProps {
  view: RowView;
  doc: Doc;
  isTrash: boolean;
  selected: boolean;
  checked: boolean;
  dimmed: boolean;
  menuOpen: boolean;
  /** The course dot is hidden inside a single course, as in the list. */
  showCourseDot: boolean;
  editing: boolean;
  draft: string;
  onDraft: (v: string) => void;
  onCommit: () => void;
  onCancel: () => void;
  onSelect: () => void;
  onOpen: () => void;
  onCheck: (e: React.MouseEvent) => void;
  onMenu: (e: React.MouseEvent) => void;
  onRestore: (e: React.MouseEvent) => void;
  onDragStart: (e: React.DragEvent) => void;
  onDragEnd: () => void;
}

export function DocCard(props: DocCardProps) {
  const {
    view, doc, isTrash, selected, checked, dimmed, menuOpen, showCourseDot,
    editing, draft, onDraft, onCommit, onCancel, onSelect, onOpen, onCheck,
    onMenu, onRestore, onDragStart, onDragEnd,
  } = props;
  const page = pagePreview(doc);

  return (
    <div
      role="button"
      tabIndex={0}
      data-testid={`library-doc-${doc.id}`}
      aria-pressed={selected}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onSelect}
      onDoubleClick={onOpen}
      onKeyDown={e => { if (e.key === "Enter") onOpen(); }}
      style={{
        animation: view.anim,
        animationDelay: view.delay,
        position: "relative", display: "flex", flexDirection: "column", borderRadius: 14,
        background: "#FDFCF9",
        border: `1px solid ${selected ? "#597536" : "rgba(42,39,31,0.12)"}`,
        boxShadow: selected
          ? "0 0 0 2px rgba(89,117,54,0.25), 0 6px 18px rgba(25,37,11,0.08)"
          : "0 1px 2px rgba(25,37,11,0.04)",
        overflow: "hidden", cursor: "pointer", opacity: dimmed ? 0.45 : 1,
      }}
    >
      <div style={{
        position: "relative", height: 176, background: "#EFEBE2",
        padding: "16px 22px 0", boxSizing: "border-box", overflow: "hidden",
      }}>
        <div style={{
          height: 220, background: "#FFFFFF", borderRadius: "4px 4px 0 0",
          boxShadow: "0 1px 3px rgba(25,37,11,0.12)", padding: "16px 16px 0",
          boxSizing: "border-box", display: "flex", flexDirection: "column", gap: 6,
        }}>
          <span style={{
            height: 4, width: 28, borderRadius: 2, background: view.courseColor || "#B9B1A0",
          }} />
          <span style={{
            fontFamily: FONT_SERIF, fontSize: 17, fontWeight: 600, lineHeight: 1.2,
          }}>{page.heading}</span>
          {page.lines.map((ln, i) => (
            <span key={i} style={{ fontSize: 10.5, lineHeight: 1.45, color: "#3F3B31" }}>{ln}</span>
          ))}
          {page.accent && (
            <span style={{ fontFamily: FONT_MONO, fontSize: 10.5, color: "#445D22" }}>
              {page.accent}
            </span>
          )}
          <span style={{ height: 5, width: "92%", borderRadius: 3, background: "#EEEAE1" }} />
          <span style={{ height: 5, width: "70%", borderRadius: 3, background: "#EEEAE1" }} />
        </div>
        <span style={{
          position: "absolute", left: 10, bottom: 10, display: "inline-flex",
          alignItems: "center", justifyContent: "center", height: 22, padding: "0 8px",
          borderRadius: 6, background: view.fmtColor,
          boxShadow: "0 1px 3px rgba(25,37,11,0.18)", fontFamily: FONT_MONO, fontSize: 11,
          fontWeight: 600, lineHeight: 1, letterSpacing: 0, color: "#FFFFFF", whiteSpace: "nowrap",
        }}>{view.fmt}</span>
      </div>

      <span style={{ position: "absolute", top: 10, left: 10 }}>
        <CheckBox
          checked={checked}
          onClick={onCheck}
          label={checked ? `Deselect ${page.heading}` : `Select ${page.heading}`}
          size={22}
          radius={6}
          background="rgba(253,252,249,0.92)"
        />
      </span>

      {isTrash ? (
        <div style={{ position: "absolute", top: 8, right: 8 }}>
          <button
            className="sapHoverChip"
            onClick={onRestore}
            style={{
              height: 32, padding: "0 12px", border: 0, borderRadius: 8, background: "#DCE8CE",
              color: "#2F4417", font: "inherit", fontSize: 13, fontWeight: 700,
              whiteSpace: "nowrap", cursor: "pointer",
            }}
          >Restore</button>
        </div>
      ) : (
        <button
          className="sapHoverCard"
          onClick={onMenu}
          aria-label="Details and actions"
          aria-haspopup="dialog"
          aria-expanded={menuOpen}
          style={{
            position: "absolute", top: 8, right: 8, width: 34, height: 34, display: "grid",
            placeItems: "center", border: 0, borderRadius: 9,
            background: menuOpen ? "#F2EEE5" : "rgba(253,252,249,0.94)",
            boxShadow: "0 1px 3px rgba(25,37,11,0.14)", color: "#3F3B31", cursor: "pointer",
          }}
        >
          <DotsIcon size={18} />
        </button>
      )}

      <div style={{
        padding: "12px 14px 14px", display: "flex", flexDirection: "column", gap: 4,
        borderTop: "1px solid rgba(42,39,31,0.10)",
        background: selected ? "#F2F6EE" : "#FDFCF9",
      }}>
        {editing && (
          <RenameInput
            value={draft} onChange={onDraft} onCommit={onCommit} onCancel={onCancel} fontSize={15}
          />
        )}
        <div style={{
          fontSize: 15, fontWeight: 600, lineHeight: 1.3,
          display: editing ? "none" : "-webkit-box",
          WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
        }}>
          {view.name.a}
          <mark style={{ background: "#D9E7C4", color: "inherit", borderRadius: 3 }}>{view.name.m}</mark>
          {view.name.b}
        </div>
        <div style={{
          display: "flex", alignItems: "center", gap: 7, fontSize: 13,
          lineHeight: "20px", color: "#6F6857",
        }}>
          <span style={{
            width: 8, height: 8, borderRadius: "50%",
            background: view.courseColor || "transparent",
            border: view.courseColor ? "0" : "1.5px dashed #8A8372",
            boxSizing: "border-box", flexShrink: 0, transform: "translateY(-0.5px)",
            display: showCourseDot ? "inline-block" : "none",
          }} />
          <span style={{
            minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>{view.cardMeta}</span>
        </div>
      </div>
    </div>
  );
}
