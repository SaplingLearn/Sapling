"use client";
/**
 * The dialog a row's "⋯" opens: Rename, Move, Add to Folder, Type, Scan to
 * Knowledge Graph, Move to Trash.
 *
 * Three things are not in the prototype's menu and are here deliberately:
 *
 *  - **Type** and **Scan to Knowledge Graph** are the old Library's per
 *    -document controls (`updateDocumentCategory`, `scanDocumentConcepts`).
 *    The redesign drops the detail panel they lived in, so they move to the
 *    closest matching spot, which is this menu (README §2.3).
 *  - The prototype's **Download** is a stub that only closes the menu. The
 *    uploaded file is not kept after processing — `document_uploads.file_data`
 *    is cleared at a terminal stage — so there is no original to hand back,
 *    and the item is left out.
 *  - The **summary and the key concepts** the pipeline extracted. v2 drops the
 *    preview panel they used to live in, and the prototype's menu does not
 *    show them — but they are the old Library's content, and the handoff is
 *    explicit that nothing may be dropped (README §2.3: keep it, in the
 *    closest matching spot). This dialog is that spot: it is what replaced the
 *    panel, and it already holds the panel's other controls.
 */
import React from "react";

import type { DocFolder, Document as Doc } from "@/lib/types";
import type { EnrolledCourse } from "@/lib/api";
import { LibraryDocNext } from "./LibraryDocNext";
import { TYPE_ORDER, TYPES, courseLabel } from "./libraryModel";
import { FolderIcon, Glyph, MENU_IN, MENU_OUT, MenuDivider, MenuScrim } from "./primitives";
import { cn } from "@/lib/cn";

/** Where the dialog sits, in the scroll section's own coordinates. */
export interface MenuPosition {
  top: string;
  bottom: string;
  right: string;
  maxHeight: string;
  origin: "top right" | "bottom right";
}

/**
 * Anchor the dialog to a row's button, flipping it above the button once the
 * button is past the half-way line — the prototype's rule, so a menu on the
 * last row opens upward instead of off the bottom.
 */
export function menuPositionFor(button: HTMLElement, section: HTMLElement): MenuPosition {
  const sr = section.getBoundingClientRect();
  // The section may be transform-scaled by a parent; divide it back out.
  const k = sr.width / section.offsetWidth || 1;
  const b = button.getBoundingClientRect();
  const height = section.offsetHeight;
  const top = (b.bottom - sr.top) / k + 6;
  const bottomEdge = (b.top - sr.top) / k - 6;
  const right = Math.max(0, (sr.right - b.right) / k);
  const up = top > height * 0.5;
  return up
    ? {
      top: "auto",
      bottom: `${height - bottomEdge}px`,
      right: `${right}px`,
      maxHeight: `${bottomEdge - 8}px`,
      origin: "bottom right",
    }
    : {
      top: `${top}px`,
      bottom: "auto",
      right: `${right}px`,
      maxHeight: `${height - top - 12}px`,
      origin: "top right",
    };
}

export type DocMenuSub = "course" | "folder" | "type" | null;

export interface DocMenuProps {
  doc: Doc;
  position: MenuPosition;
  closing: boolean;
  courses: EnrolledCourse[];
  folders: DocFolder[];
  sub: DocMenuSub;
  onSub: (s: DocMenuSub) => void;
  onClose: () => void;
  onRename: () => void;
  onMoveCourse: (courseId: string | null) => void;
  onMoveFolder: (folderId: string | null) => void;
  onType: (c: Doc["category"]) => void;
  onScan: () => void;
  scanState: "idle" | "scanning" | "done";
  onTrash: () => void;
}

/**
 * What the pipeline read out of the document: its summary, and the concepts it
 * linked to the knowledge graph. The old Library showed these in a panel that
 * v2 removes; they are kept here rather than lost.
 *
 * A concept's description is markdown in the old panel. Here it is the plain
 * name, with the description as its tooltip — the dialog is 240px wide.
 */
function DocumentFacts({ doc }: { doc: Doc }) {
  const concepts = doc.concept_notes ?? [];
  if (!doc.summary && !concepts.length) return null;

  return (
    <>
      <MenuDivider />
      {doc.summary && (
        <>
          <span className="pt-1.5 px-2.5 pb-1 font-sans text-md text-[#6F6857]">Summary</span>
          <p className="m-0 pt-0 px-2.5 pb-1.5 text-md leading-[1.5] text-ink-600 text-pretty">{doc.summary}</p>
        </>
      )}
      {concepts.length > 0 && (
        <>
          <span className="pt-1.5 px-2.5 pb-1 font-sans text-md text-[#6F6857]">Key Concepts ({concepts.length})</span>
          <div className="flex flex-wrap gap-1 pt-0 px-2.5 pb-2">
            {concepts.map((c, i) => (
              <span
                key={`${c.name}-${i}`}
                title={c.description || undefined}
                className="inline-flex items-center h-5.5 py-0 px-2 rounded-sm bg-[#EBF0E1] text-leaf-800 text-[12.5px] font-semibold"
              >{c.name}</span>
            ))}
          </div>
        </>
      )}
    </>
  );
}

export function DocMenu(props: DocMenuProps) {
  const {
    doc, position, closing, courses, folders, sub, onSub, onClose, onRename,
    onMoveCourse, onMoveFolder, onType, onScan, scanState, onTrash,
  } = props;

  const anim = closing ? MENU_OUT : MENU_IN;
  // A folder lives inside a course, so only this document's course offers any.
  const ownFolders = folders.filter(f => (f.course_id || null) === (doc.course_id || null));

  const expander = (label: string, key: Exclude<DocMenuSub, null>) => (
    <button
      role="menuitem"
      aria-expanded={sub === key}
      className="sapHoverMenu flex items-center gap-2.5 py-[9px] px-2.5 border-0 rounded-[8px] [background:transparent] text-ink-800 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-semibold text-left cursor-pointer w-full"
      onClick={() => onSub(sub === key ? null : key)}
    >
      <span className="flex-1">{label}</span>
      <span className={cn("inline-flex", sub === key ? "[transform:rotate(180deg)]" : "[transform:none]")}>
        <Glyph name="chevronDown" size={11} fill="#6F6857" />
      </span>
    </button>
  );

  const option = (
    key: string,
    label: string,
    on: boolean,
    pick: () => void,
    icon?: React.ReactNode,
  ) => (
    <button
      key={key}
      role="menuitemradio"
      aria-checked={on}
      className="sapHoverMenu flex items-center gap-2.5 py-2 px-2.5 border-0 rounded-[8px] [background:transparent] [font-family:inherit] [font-weight:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base text-left cursor-pointer"
      onClick={pick}
    >
      {icon}
      <span className="flex-1">{label}</span>
      <Glyph name="check" size={12} fill="#445D22" style={{ opacity: on ? 1 : 0 }} />
    </button>
  );

  const subList = (children: React.ReactNode) => (
    <div role="group" className="flex flex-col gap-px pl-2.5">
      {children}
    </div>
  );

  return (
    <>
      <MenuScrim onClick={onClose} />
      <div
        role="dialog"
        aria-label="Document details"
        data-testid="library-doc-menu"
        className="absolute z-31 w-60 bg-bg-panel border border-[rgba(42,39,31,0.14)] rounded-[12px] [box-shadow:0_14px_36px_rgba(25,37,11,0.16)] flex flex-col overflow-y-auto" style={{ transformOrigin: position.origin, animation: anim, right: position.right, top: position.top, bottom: position.bottom, maxHeight: position.maxHeight }}
      >
        <div className="p-1.5 flex flex-col gap-px">
          {/* The actions are menus inside the dialog (its facts and next steps
              between them are not menu items), so every menuitem has the
              parent ARIA requires. `display: contents` keeps the layout. */}
          <div role="menu" aria-label="Document actions" className="contents">
          <button role="menuitem" className="sapHoverMenu flex items-center gap-2.5 py-[9px] px-2.5 border-0 rounded-[8px] [background:transparent] text-ink-800 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-semibold text-left cursor-pointer" onClick={onRename}>
            Rename
          </button>

          <MenuDivider />

          {expander("Move", "course")}
          {sub === "course" && subList(
            <>
              {courses.map(c => option(
                c.course_id,
                `${courseLabel(c)} · ${c.course_name}`,
                doc.course_id === c.course_id,
                () => onMoveCourse(c.course_id),
                <span className={cn("w-[9px] h-[9px] rounded-[50%] box-border", c.color ? "border-0" : "border-[1.5px] border-dashed border-ink-400")} style={{ background: c.color || "transparent" }} />,
              ))}
              {option(
                "none",
                "No Course",
                !doc.course_id,
                () => onMoveCourse(null),
                <span className="w-[9px] h-[9px] rounded-[50%] bg-transparent border-[1.5px] border-dashed border-ink-400 box-border" />,
              )}
            </>,
          )}

          {ownFolders.length > 0 && (
            <>
              {expander("Add to Folder", "folder")}
              {sub === "folder" && subList(
                ownFolders.map(f => option(
                  f.id,
                  f.name,
                  doc.folder_id === f.id,
                  // Picking the folder it is already in takes it out again,
                  // which is how the prototype's toggle behaves.
                  () => onMoveFolder(doc.folder_id === f.id ? null : f.id),
                  <FolderIcon size={14} />,
                )),
              )}
            </>
          )}

          {expander("Type", "type")}
          {sub === "type" && subList(
            TYPE_ORDER.map(c => option(
              c,
              TYPES[c].label,
              doc.category === c,
              () => onType(c),
              <span className="w-[9px] h-[9px] rounded-[2px] box-border" style={{ background: TYPES[c].color }} />,
            )),
          )}

          <button
            role="menuitem"
            data-testid="library-detail-scan"
            className={cn("sapHoverMenu", "flex items-center gap-2.5 py-[9px] px-2.5 border-0 rounded-[8px] [background:transparent] text-ink-800 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-semibold text-left", scanState === "scanning" ? "cursor-default" : "cursor-pointer")}
            onClick={onScan}
            disabled={scanState === "scanning"}
            title="Extend this course's concept graph from this document"
          >
            <span className="flex-1">
              {scanState === "scanning"
                ? "Scanning…"
                : scanState === "done" ? "Scanned ✓" : "Scan to Knowledge Graph"}
            </span>
          </button>
          </div>

          <DocumentFacts doc={doc} />
          <LibraryDocNext doc={doc} />

          <MenuDivider />

          <div role="menu" aria-label="Remove" className="contents">
          <button
            role="menuitem"
            data-testid="library-detail-delete"
            className="sapHoverDanger flex items-center gap-2.5 py-[9px] px-2.5 border-0 rounded-[8px] [background:transparent] [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base text-left cursor-pointer text-[#A8443F] font-bold"
            onClick={onTrash}
          >
            Move to Trash
          </button>
          </div>
        </div>
      </div>
    </>
  );
}
