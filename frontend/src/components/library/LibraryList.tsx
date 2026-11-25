"use client";
/**
 * List view: the column header, the folder rows that sit above the documents
 * at a course root, and the document rows themselves.
 *
 * Rows are grids on a shared track list so the header and the rows line up;
 * `rowModel.ts` computes what each one shows.
 */
import React from "react";

import type { DocFolder, Document as Doc } from "@/lib/types";
import {
  CheckBox, ChevronRight, DotsIcon, FOLDER_TILE, FolderIcon, FONT_MONO,
} from "./primitives";
import type { RowView } from "./rowModel";

/** The in-place rename input a new or renamed row shows instead of its title. */
export function RenameInput({
  value, onChange, onCommit, onCancel, fontSize = 16,
}: {
  value: string;
  onChange: (v: string) => void;
  onCommit: () => void;
  onCancel: () => void;
  fontSize?: number;
}) {
  return (
    <input
      autoFocus
      onFocus={e => e.currentTarget.select()}
      value={value}
      onChange={e => onChange(e.target.value)}
      onKeyDown={e => {
        if (e.key === "Enter") e.currentTarget.blur();
        if (e.key === "Escape") { onCancel(); }
      }}
      onBlur={onCommit}
      onClick={e => e.stopPropagation()}
      aria-label="Name"
      style={{
        width: "100%", boxSizing: "border-box", height: 30, padding: "0 8px",
        border: "1.5px solid #597536", borderRadius: 7, background: "#FFFFFF",
        font: "inherit", fontSize, fontWeight: 600, color: "#1A1814", outline: "none",
      }}
    />
  );
}

export interface ListHeaderProps {
  columns: string;
  showCourse: boolean;
  allChecked: boolean;
  onToggleAll: () => void;
}

export function ListHeader({ columns, showCourse, allChecked, onToggleAll }: ListHeaderProps) {
  return (
    <div role="row" style={{
      display: "grid", gridTemplateColumns: columns, gap: 12, minWidth: 0,
      alignItems: "center", padding: "12px 14px 8px",
      fontSize: 13, fontWeight: 600, color: "#6F6857",
    }}>
      <CheckBox checked={allChecked} onClick={onToggleAll} label="Select all" />
      <span>Name</span>
      {showCourse && <span>Course</span>}
      <span>Type</span>
      <span style={{ textAlign: "right" }}>Pages</span>
      <span style={{ textAlign: "right" }}>Added</span>
      <span />
    </div>
  );
}

export interface FolderRowProps {
  folder: DocFolder;
  columns: string;
  showCourse: boolean;
  count: number;
  selected: boolean;
  dragOver: boolean;
  delay: string;
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

export function FolderRow(props: FolderRowProps) {
  const {
    folder, columns, showCourse, count, selected, dragOver, delay, editing, draft,
    onDraft, onCommit, onCancel, onSelect, onOpen, onDragOver, onDragLeave, onDrop,
  } = props;
  return (
    <div
      role="row"
      tabIndex={0}
      data-testid={`library-folder-${folder.id}`}
      aria-selected={selected}
      data-on={selected ? "1" : "0"}
      className="sapRow"
      onClick={onSelect}
      onDoubleClick={onOpen}
      onKeyDown={e => { if (e.key === "Enter") onOpen(); }}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      style={{
        animation: "sapSlideUp 420ms cubic-bezier(0.2, 0.7, 0.2, 1) 0ms both",
        animationDelay: delay,
        display: "grid", gridTemplateColumns: columns, gap: 12, minWidth: 0,
        alignItems: "center", padding: "10px 14px", borderRadius: 12,
        background: dragOver ? "#DCE8CE" : selected ? "#EDE9E0" : "transparent",
        boxShadow: dragOver ? "inset 0 0 0 1.5px #597536" : "none",
        cursor: "pointer",
      }}
    >
      <span />
      <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
        <span style={FOLDER_TILE}><FolderIcon size={30} strokeWidth={1.6} /></span>
        <div style={{ minWidth: 0, flex: 1 }}>
          {editing && (
            <RenameInput value={draft} onChange={onDraft} onCommit={onCommit} onCancel={onCancel} />
          )}
          <div style={{
            fontSize: 16, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden",
            textOverflow: "ellipsis", display: editing ? "none" : "block",
          }}>{folder.name}</div>
          <div style={{ fontSize: 14, color: "#6F6857" }}>
            {count} {count === 1 ? "document" : "documents"}
          </div>
        </div>
      </div>
      {showCourse && <span />}
      <span style={{ fontSize: 14, color: "#3F3B31" }}>Folder</span>
      <span style={{ fontSize: 14, color: "#8A8372", textAlign: "right" }}>—</span>
      <span style={{ display: "flex", justifyContent: "flex-end", color: "#6F6857" }}>
        <ChevronRight size={12} />
      </span>
      <span />
    </div>
  );
}

export interface DocRowProps {
  view: RowView;
  doc: Doc;
  columns: string;
  showCourse: boolean;
  isTrash: boolean;
  selected: boolean;
  checked: boolean;
  dimmed: boolean;
  menuOpen: boolean;
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

export function DocRow(props: DocRowProps) {
  const {
    view, doc, columns, showCourse, isTrash, selected, checked, dimmed, menuOpen,
    editing, draft, onDraft, onCommit, onCancel, onSelect, onOpen, onCheck, onMenu,
    onRestore, onDragStart, onDragEnd,
  } = props;

  return (
    <div
      role="row"
      tabIndex={0}
      data-testid={`library-doc-${doc.id}`}
      aria-selected={selected}
      data-on={selected ? "1" : "0"}
      className="sapRow"
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onSelect}
      onDoubleClick={onOpen}
      onKeyDown={e => { if (e.key === "Enter") onOpen(); }}
      style={{
        animation: view.anim,
        animationDelay: view.delay,
        display: "grid", gridTemplateColumns: columns, gap: 12, minWidth: 0,
        alignItems: "center", padding: "12px 14px", borderRadius: 12,
        // The current row (a click, or the arrow keys) is a neutral tint with no
        // outline, so it never reads as checked or as the green selection bar.
        background: selected ? "#EDE9E0" : "transparent",
        cursor: "pointer",
        opacity: dimmed ? 0.45 : 1,
      }}
    >
      <CheckBox
        checked={checked}
        onClick={onCheck}
        label={checked ? `Deselect ${view.name.a}${view.name.m}${view.name.b}`
                       : `Select ${view.name.a}${view.name.m}${view.name.b}`}
      />

      <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
        <span
          title={`${view.typeLabel} · ${view.fmt}`}
          style={{
            width: 30, height: 38, borderRadius: 5, background: view.fmtColor, color: "#FFFFFF",
            display: "grid", placeItems: "center", boxSizing: "border-box",
            fontFamily: FONT_MONO, fontSize: 8, fontWeight: 600, lineHeight: 1,
            letterSpacing: 0, textAlign: "center", flexShrink: 0,
          }}
        >{view.fmt}</span>
        <div style={{ minWidth: 0 }}>
          {editing && (
            <RenameInput value={draft} onChange={onDraft} onCommit={onCommit} onCancel={onCancel} />
          )}
          <div style={{
            fontSize: 16, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden",
            textOverflow: "ellipsis", display: editing ? "none" : "block",
          }}>
            {view.name.a}
            <mark style={{ background: "#D9E7C4", color: "inherit", borderRadius: 3 }}>{view.name.m}</mark>
            {view.name.b}
          </div>
          <div style={{
            fontSize: 14, color: view.subColor, whiteSpace: "nowrap",
            overflow: "hidden", textOverflow: "ellipsis",
          }}>{view.sub}</div>
        </div>
      </div>

      {showCourse && (
        <span style={{ display: "flex", alignItems: "center", minWidth: 0, fontSize: 14 }}>
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 8, minWidth: 0, maxWidth: "100%",
            height: 20, lineHeight: "20px", color: view.courseColor ? "#1A1814" : "#6F6857",
          }}>
            <span style={{
              width: 8, height: 8, borderRadius: "50%",
              background: view.courseColor || "transparent",
              border: view.courseColor ? "0" : "1.5px dashed #8A8372",
              boxSizing: "border-box", flexShrink: 0,
            }} />
            <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {view.courseLabel}
            </span>
          </span>
        </span>
      )}

      <span style={{ fontSize: 14, color: "#3F3B31" }}>{view.typeLabel}</span>
      <span style={{
        fontSize: 14, color: view.pages ? "#3F3B31" : "#8A8372",
        textAlign: "right", fontVariantNumeric: "tabular-nums",
      }}>{view.pages || "—"}</span>
      <span style={{ fontSize: 14, color: "#6F6857", textAlign: "right" }}>{view.added}</span>

      {isTrash ? (
        <span style={{ justifySelf: "end" }}>
          <button
            className="sapHoverChip"
            onClick={onRestore}
            style={{
              height: 32, padding: "0 12px", border: 0, borderRadius: 8, background: "#DCE8CE",
              color: "#2F4417", font: "inherit", fontSize: 13, fontWeight: 700,
              whiteSpace: "nowrap", cursor: "pointer",
            }}
          >Restore</button>
        </span>
      ) : (
        <button
          className="sapHoverStone"
          onClick={onMenu}
          aria-label="Details and actions"
          aria-haspopup="dialog"
          aria-expanded={menuOpen}
          style={{
            justifySelf: "end", width: 36, height: 36, display: "grid", placeItems: "center",
            border: 0, borderRadius: 9, background: menuOpen ? "#E4DFD3" : "transparent",
            color: "#3F3B31", cursor: "pointer",
          }}
        >
          <DotsIcon size={18} />
        </button>
      )}
    </div>
  );
}
