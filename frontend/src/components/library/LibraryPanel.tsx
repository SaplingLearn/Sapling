"use client";
/**
 * Panel view: the same folders and documents as the list, as cards with a
 * miniature of the document's first page.
 */
import React from "react";

import type { DocFolder, Document as Doc } from "@/lib/types";
import { CheckBox, DotsIcon, FolderIcon } from "./primitives";
import { RenameInput } from "./LibraryList";
import { pagePreview, type RowView } from "./rowModel";
import { cn } from "@/lib/cn";

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
      className={cn("flex flex-col rounded-[14px] bg-bg-panel [box-shadow:0_1px_2px_rgba(25,37,11,0.04)] overflow-hidden cursor-pointer", dragOver || selected ? "border border-brand-forest-bright" : "border border-[rgba(42,39,31,0.12)]")}
    >
      <div className={cn("h-44 grid place-items-center", dragOver ? "bg-[#DCE8CE]" : "bg-[#EFEBE2]")}>
        <FolderIcon size={84} strokeWidth={1.6} />
      </div>
      <div className="pt-3 px-3.5 pb-3.5 flex flex-col gap-1 border-t border-t-[rgba(42,39,31,0.10)]">
        {editing && (
          <RenameInput
            value={draft} onChange={onDraft} onCommit={onCommit} onCancel={onCancel} fontSize={15}
          />
        )}
        <div className={cn("text-[15px] font-semibold leading-[1.3]", editing ? "hidden" : "block")}>{folder.name}</div>
        <div className="text-md text-text-muted">
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
      className={cn(cn("relative flex flex-col rounded-[14px] bg-bg-panel overflow-hidden cursor-pointer", selected ? "[box-shadow:0_0_0_2px_rgba(89,117,54,0.25),_0_6px_18px_rgba(25,37,11,0.08)]" : "[box-shadow:0_1px_2px_rgba(25,37,11,0.04)]", dimmed ? "opacity-45" : "opacity-100"), selected ? "border border-brand-forest-bright" : "border border-[rgba(42,39,31,0.12)]")} style={{ animation: view.anim, animationDelay: view.delay }}
    >
      <div className="relative h-44 bg-[#EFEBE2] pt-4 px-5.5 pb-0 box-border overflow-hidden">
        <div className="h-55 bg-accent-fg [border-radius:4px_4px_0_0] [box-shadow:0_1px_3px_rgba(25,37,11,0.12)] pt-4 px-4 pb-0 box-border flex flex-col gap-1.5">
          <span className="h-1 w-7 rounded-[2px]" style={{ background: view.courseColor || "#B9B1A0" }} />
          <span className="font-serif text-[17px] font-semibold leading-[1.2]">{page.heading}</span>
          {page.lines.map((ln, i) => (
            <span key={i} className="text-[10.5px] leading-[1.45] text-ink-600">{ln}</span>
          ))}
          {page.accent && (
            <span className="font-sans text-[10.5px] text-brand-forest">
              {page.accent}
            </span>
          )}
          <span className="h-[5px] w-[92%] rounded-[3px] bg-[#EEEAE1]" />
          <span className="h-[5px] w-[70%] rounded-[3px] bg-[#EEEAE1]" />
        </div>
        <span className="absolute left-2.5 bottom-2.5 inline-flex items-center justify-center h-5.5 py-0 px-2 rounded-sm [box-shadow:0_1px_3px_rgba(25,37,11,0.18)] font-sans text-xs font-semibold leading-none tracking-[0] text-accent-fg whitespace-nowrap" style={{ background: view.fmtColor }}>{view.fmt}</span>
      </div>

      <span className="absolute top-2.5 left-2.5">
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
        <div className="absolute top-2 right-2">
          <button
            className="sapHoverChip h-8 py-0 px-3 border-0 rounded-[8px] [background:#DCE8CE] text-leaf-800 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-md font-bold whitespace-nowrap cursor-pointer"
            onClick={onRestore}
          >Restore</button>
        </div>
      ) : (
        <button
          className={cn("sapHoverCard", "absolute top-2 right-2 w-8.5 h-8.5 grid place-items-center border-0 rounded-[9px] [box-shadow:0_1px_3px_rgba(25,37,11,0.14)] text-ink-600 cursor-pointer", menuOpen ? "[background:#F2EEE5]" : "[background:rgba(253,252,249,0.94)]")}
          onClick={onMenu}
          aria-label="Details and actions"
          aria-haspopup="dialog"
          aria-expanded={menuOpen}
        >
          <DotsIcon size={18} />
        </button>
      )}

      <div className={cn("pt-3 px-3.5 pb-3.5 flex flex-col gap-1 border-t border-t-[rgba(42,39,31,0.10)]", selected ? "bg-sap-50" : "bg-bg-panel")}>
        {editing && (
          <RenameInput
            value={draft} onChange={onDraft} onCommit={onCommit} onCancel={onCancel} fontSize={15}
          />
        )}
        <div className={cn("text-[15px] font-semibold leading-[1.3] [-webkit-line-clamp:2] [-webkit-box-orient:vertical] overflow-hidden", editing ? "hidden" : "[display:-webkit-box]")}>
          {view.name.a}
          <mark className="bg-leaf-100 text-inherit rounded-[3px]">{view.name.m}</mark>
          {view.name.b}
        </div>
        <div className="flex items-center gap-[7px] text-md leading-[20px] text-text-muted">
          <span className={cn("w-2 h-2 rounded-[50%] box-border shrink-0 [transform:translateY(-0.5px)]", view.courseColor ? "border-0" : "border-[1.5px] border-dashed border-ink-400", showCourseDot ? "inline-block" : "hidden")} style={{ background: view.courseColor || "transparent" }} />
          <span className="min-w-0 whitespace-nowrap overflow-hidden text-ellipsis">{view.cardMeta}</span>
        </div>
      </div>
    </div>
  );
}
