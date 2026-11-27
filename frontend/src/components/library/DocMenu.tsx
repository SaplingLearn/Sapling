"use client";
/**
 * The dialog a row's "⋯" opens: Open, Rename, Download Notes, Move, Add to
 * Folder, Type, Scan to Knowledge Graph, Move to Trash.
 *
 * Three things are not in the prototype's menu and are here deliberately:
 *
 *  - **Type** and **Scan to Knowledge Graph** are the old Library's per
 *    -document controls (`updateDocumentCategory`, `scanDocumentConcepts`).
 *    The redesign drops the detail panel they lived in, so they move to the
 *    closest matching spot, which is this menu (README §2.3).
 *  - The prototype's **Download** is a stub that only closes the menu. The
 *    uploaded file is not kept after processing — `document_uploads.file_data`
 *    is cleared at a terminal stage — so there is no original to hand back.
 *    It downloads the document's notes instead, and says so.
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
import { TYPE_ORDER, TYPES, courseLabel } from "./libraryModel";
import {
  ChevronRight, FolderIcon, Glyph, MENU_HEADING, MENU_IN, MENU_ITEM, MENU_OUT,
  MenuDivider, MenuScrim,
} from "./primitives";

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
  onOpen: () => void;
  onRename: () => void;
  onDownload: () => void;
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
 * name — the dialog is 240px wide, and the description belongs on the Notes
 * page, which is a click away under Open.
 */
function DocumentFacts({ doc }: { doc: Doc }) {
  const concepts = doc.concept_notes ?? [];
  if (!doc.summary && !concepts.length) return null;

  return (
    <>
      <MenuDivider />
      {doc.summary && (
        <>
          <span style={MENU_HEADING}>Summary</span>
          <p style={{
            margin: 0, padding: "0 10px 6px", fontSize: 13, lineHeight: 1.5,
            color: "#3F3B31", textWrap: "pretty",
          }}>{doc.summary}</p>
        </>
      )}
      {concepts.length > 0 && (
        <>
          <span style={MENU_HEADING}>Key Concepts ({concepts.length})</span>
          <div style={{
            display: "flex", flexWrap: "wrap", gap: 4, padding: "0 10px 8px",
          }}>
            {concepts.map((c, i) => (
              <span
                key={`${c.name}-${i}`}
                title={c.description || undefined}
                style={{
                  display: "inline-flex", alignItems: "center", height: 22,
                  padding: "0 8px", borderRadius: 6, background: "#EBF0E1",
                  color: "#2F4417", fontSize: 12.5, fontWeight: 600,
                }}
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
    doc, position, closing, courses, folders, sub, onSub, onClose, onOpen, onRename,
    onDownload, onMoveCourse, onMoveFolder, onType, onScan, scanState, onTrash,
  } = props;

  const anim = closing ? MENU_OUT : MENU_IN;
  // A folder lives inside a course, so only this document's course offers any.
  const ownFolders = folders.filter(f => (f.course_id || null) === (doc.course_id || null));

  const expander = (label: string, key: Exclude<DocMenuSub, null>) => (
    <button
      role="menuitem"
      aria-expanded={sub === key}
      className="sapHoverMenu"
      onClick={() => onSub(sub === key ? null : key)}
      style={{ ...MENU_ITEM, width: "100%" }}
    >
      <span style={{ flex: 1 }}>{label}</span>
      <span style={{
        display: "inline-flex",
        transform: sub === key ? "rotate(180deg)" : "none",
      }}>
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
      className="sapHoverMenu"
      onClick={pick}
      style={{
        display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", border: 0,
        borderRadius: 8, background: "transparent", font: "inherit", fontSize: 14,
        textAlign: "left", cursor: "pointer",
      }}
    >
      {icon}
      <span style={{ flex: 1 }}>{label}</span>
      <Glyph name="check" size={12} fill="#445D22" style={{ opacity: on ? 1 : 0 }} />
    </button>
  );

  const subList = (children: React.ReactNode) => (
    <div style={{ display: "flex", flexDirection: "column", gap: 1, paddingLeft: 10 }}>
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
        style={{
          transformOrigin: position.origin,
          animation: anim,
          position: "absolute",
          right: position.right,
          top: position.top,
          bottom: position.bottom,
          maxHeight: position.maxHeight,
          zIndex: 31,
          width: 240,
          background: "#FDFCF9",
          border: "1px solid rgba(42,39,31,0.14)",
          borderRadius: 12,
          boxShadow: "0 14px 36px rgba(25,37,11,0.16)",
          display: "flex",
          flexDirection: "column",
          overflowY: "auto",
        }}
      >
        <div style={{ padding: 6, display: "flex", flexDirection: "column", gap: 1 }}>
          <button
            role="menuitem"
            className="sapHoverMenu"
            onClick={onOpen}
            style={{ ...MENU_ITEM, color: "#2F4417", fontWeight: 700 }}
          >
            <span style={{ flex: 1 }}>Open</span>
            <ChevronRight size={12} />
          </button>
          <button role="menuitem" className="sapHoverMenu" onClick={onRename} style={MENU_ITEM}>
            Rename
          </button>
          <button
            role="menuitem"
            className="sapHoverMenu"
            onClick={onDownload}
            title="The original file isn't kept after processing; this downloads the notes."
            style={MENU_ITEM}
          >
            Download Notes
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
                <span style={{
                  width: 9, height: 9, borderRadius: "50%",
                  background: c.color || "transparent",
                  border: c.color ? "0" : "1.5px dashed #8A8372",
                  boxSizing: "border-box",
                }} />,
              ))}
              {option(
                "none",
                "No Course",
                !doc.course_id,
                () => onMoveCourse(null),
                <span style={{
                  width: 9, height: 9, borderRadius: "50%", background: "transparent",
                  border: "1.5px dashed #8A8372", boxSizing: "border-box",
                }} />,
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
              <span style={{
                width: 9, height: 9, borderRadius: 2, background: TYPES[c].color,
                boxSizing: "border-box",
              }} />,
            )),
          )}

          <button
            role="menuitem"
            data-testid="library-detail-scan"
            className="sapHoverMenu"
            onClick={onScan}
            disabled={scanState === "scanning"}
            title="Extend this course's concept graph from this document"
            style={{ ...MENU_ITEM, cursor: scanState === "scanning" ? "default" : "pointer" }}
          >
            <span style={{ flex: 1 }}>
              {scanState === "scanning"
                ? "Scanning…"
                : scanState === "done" ? "Scanned ✓" : "Scan to Knowledge Graph"}
            </span>
          </button>

          <DocumentFacts doc={doc} />

          <MenuDivider />

          <button
            role="menuitem"
            data-testid="library-detail-delete"
            className="sapHoverDanger"
            onClick={onTrash}
            style={{ ...MENU_ITEM, color: "#A8443F", fontWeight: 700 }}
          >
            Move to Trash
          </button>
        </div>
      </div>
    </>
  );
}
