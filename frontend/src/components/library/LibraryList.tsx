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
import { CheckBox, ChevronRight, DotsIcon, FolderIcon } from "./primitives";
import type { RowView } from "./rowModel";
import { cn } from "@/lib/cn";

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
      className="w-full box-border h-7.5 py-0 px-2 border-[1.5px] border-brand-forest-bright rounded-[7px] bg-sidenav-fg [font-family:inherit] [font-size:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] font-semibold text-ink-800 outline-none" style={{ fontSize }}
    />
  );
}

export interface ListHeaderProps {
  columns: string;
  showCourse: boolean;
  allChecked: boolean;
  onToggleAll: () => void;
}

/**
 * A grid cell around a control that is itself the column's grid item:
 * `display: contents` keeps the control as the grid child (no layout change)
 * while the accessibility tree gets the cell a `row` requires (axe
 * aria-required-children; the list is `role="grid"`, LibraryBody).
 */
function Cell({ header = false, children }: { header?: boolean; children: React.ReactNode }) {
  return (
    <span role={header ? "columnheader" : "gridcell"} className="contents">
      {children}
    </span>
  );
}

export function ListHeader({ columns, showCourse, allChecked, onToggleAll }: ListHeaderProps) {
  return (
    <div role="row" className="grid gap-3 min-w-0 items-center pt-3 px-3.5 pb-2 text-md font-semibold text-[#6F6857]" style={{ gridTemplateColumns: columns }}>
      <Cell header>
        <CheckBox checked={allChecked} onClick={onToggleAll} label="Select all" />
      </Cell>
      <span role="columnheader">Name</span>
      {showCourse && <span role="columnheader">Course</span>}
      <span role="columnheader">Type</span>
      <span role="columnheader" className="text-right">Pages</span>
      <span role="columnheader" className="text-right">Added</span>
      <span role="columnheader" aria-label="Actions" />
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
      className={cn("sapRow", "[animation:sapSlideUp_420ms_cubic-bezier(0.2,_0.7,_0.2,_1)_0ms_both] grid gap-3 min-w-0 items-center py-2.5 px-3.5 rounded-[12px] cursor-pointer", dragOver ? "[box-shadow:inset_0_0_0_1.5px_#597536]" : "shadow-none")}
      onClick={onSelect}
      onDoubleClick={onOpen}
      onKeyDown={e => { if (e.key === "Enter") onOpen(); }}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      style={{ animationDelay: delay, gridTemplateColumns: columns, background: dragOver ? "#DCE8CE" : selected ? "#EDE9E0" : "transparent" }}
    >
      <span role="gridcell" />
      <div role="gridcell" className="flex items-center gap-3.5 min-w-0">
        <span className="w-7.5 h-9.5 grid place-items-center shrink-0"><FolderIcon size={30} strokeWidth={1.6} /></span>
        <div className="min-w-0 flex-1">
          {editing && (
            <RenameInput value={draft} onChange={onDraft} onCommit={onCommit} onCancel={onCancel} />
          )}
          <div className={cn("text-lg font-semibold whitespace-nowrap overflow-hidden text-ellipsis", editing ? "hidden" : "block")}>{folder.name}</div>
          <div className="text-base text-[#6F6857]">
            {count} {count === 1 ? "document" : "documents"}
          </div>
        </div>
      </div>
      {showCourse && <span role="gridcell" />}
      <span role="gridcell" className="text-base text-ink-600">Folder</span>
      <span role="gridcell" className="text-base text-ink-400 text-right">—</span>
      <span role="gridcell" className="flex justify-end text-[#6F6857]">
        <ChevronRight size={12} />
      </span>
      <span role="gridcell" />
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
      className={cn("sapRow", "grid gap-3 min-w-0 items-center py-3 px-3.5 rounded-[12px] cursor-pointer", selected ? "[background:#EDE9E0]" : "[background:transparent]", dimmed ? "opacity-45" : "opacity-100")}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onSelect}
      onDoubleClick={onOpen}
      onKeyDown={e => { if (e.key === "Enter") onOpen(); }}
      style={{ animation: view.anim, animationDelay: view.delay, gridTemplateColumns: columns }}
    >
      <Cell>
        <CheckBox
          checked={checked}
          onClick={onCheck}
          label={checked ? `Deselect ${view.name.a}${view.name.m}${view.name.b}`
                         : `Select ${view.name.a}${view.name.m}${view.name.b}`}
        />
      </Cell>

      <div role="gridcell" className="flex items-center gap-3.5 min-w-0">
        <span
          title={`${view.typeLabel} · ${view.fmt}`}
          className="w-7.5 h-9.5 rounded-[5px] text-sidenav-fg grid place-items-center box-border font-sans text-[8px] font-semibold leading-none tracking-[0] text-center shrink-0" style={{ background: view.fmtColor }}
        >{view.fmt}</span>
        <div className="min-w-0">
          {editing && (
            <RenameInput value={draft} onChange={onDraft} onCommit={onCommit} onCancel={onCancel} />
          )}
          <div className={cn("text-lg font-semibold whitespace-nowrap overflow-hidden text-ellipsis", editing ? "hidden" : "block")}>
            {view.name.a}
            <mark className="bg-leaf-100 text-inherit rounded-[3px]">{view.name.m}</mark>
            {view.name.b}
          </div>
          <div className="text-base whitespace-nowrap overflow-hidden text-ellipsis" style={{ color: view.subColor }}>{view.sub}</div>
        </div>
      </div>

      {showCourse && (
        <span role="gridcell" className="flex items-center min-w-0 text-base">
          <span className={cn("inline-flex items-center gap-2 min-w-0 max-w-full h-5 leading-[20px]", view.courseColor ? "text-ink-800" : "text-[#6F6857]")}>
            <span className={cn("w-2 h-2 rounded-[50%] box-border shrink-0", view.courseColor ? "border-0" : "border-[1.5px] border-dashed border-ink-400")} style={{ background: view.courseColor || "transparent" }} />
            <span className="whitespace-nowrap overflow-hidden text-ellipsis">
              {view.courseLabel}
            </span>
          </span>
        </span>
      )}

      <span role="gridcell" className="text-base text-ink-600">{view.typeLabel}</span>
      <span role="gridcell" className={cn("text-base text-right tabular-nums", view.pages ? "text-ink-600" : "text-ink-400")}>{view.pages || "—"}</span>
      <span role="gridcell" className="text-base text-[#6F6857] text-right">{view.added}</span>

      {isTrash ? (
        <span role="gridcell" className="[justify-self:end]">
          <button
            className="sapHoverChip h-8 py-0 px-3 border-0 rounded-[8px] [background:#DCE8CE] text-leaf-800 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-md font-bold whitespace-nowrap cursor-pointer"
            onClick={onRestore}
          >Restore</button>
        </span>
      ) : (
        <Cell>
        <button
          className={cn("sapHoverStone", "[justify-self:end] w-9 h-9 grid place-items-center border-0 rounded-[9px] text-ink-600 cursor-pointer", menuOpen ? "[background:#E4DFD3]" : "[background:transparent]")}
          onClick={onMenu}
          aria-label="Details and actions"
          aria-haspopup="dialog"
          aria-expanded={menuOpen}
        >
          <DotsIcon size={18} />
        </button>
        </Cell>
      )}
    </div>
  );
}
