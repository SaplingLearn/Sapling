"use client";
import React from "react";
import type { Document as Doc } from "@/lib/types";
import styles from "./Library.module.css";
import { FMT_COLORS, addedLabel, displayTitle, fileFormat, pageOf, type CourseInfo } from "./model";
import { CourseDot, FolderIcon, PageCard, Tinted, menuHeading, menuItemStyle, menuPanel } from "./parts";
import { INHERIT_FONT } from "@/lib/inheritFont";

export interface FolderOption { id: string; name: string; on: boolean }

export function LibraryPreview({
  doc, course, folderName, folderOptions, renaming, onStartRename, onEndRename, onToggleFolder, onDelete, onOpen,
}: {
  doc: Doc | null;
  course: CourseInfo | null;
  folderName: string | null;
  folderOptions: FolderOption[];
  renaming: boolean;
  onStartRename: () => void;
  onEndRename: (name: string | null) => void;
  onToggleFolder: (folderId: string) => void;
  onDelete: () => void;
  onOpen: () => void;
}) {
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [confirmDel, setConfirmDel] = React.useState(false);
  const [draft, setDraft] = React.useState("");
  const cancelRef = React.useRef(false);
  const docId = doc?.id;

  React.useEffect(() => { setMenuOpen(false); setConfirmDel(false); }, [docId]);
  React.useEffect(() => {
    if (renaming && doc) { setDraft(displayTitle(doc.file_name)); setMenuOpen(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renaming, docId]);

  const closeMenu = () => { setMenuOpen(false); setConfirmDel(false); };

  return (
    <aside
      aria-label="Selected material"
      data-testid="library-preview"
      className={styles.scroll}
      style={{
        position: "relative", gridColumn: 3, gridRow: 2, alignSelf: "start", maxHeight: "calc(100% - 28px)",
        padding: "22px 24px 24px", background: "#E6EDDC", borderRadius: 16, display: "flex", flexDirection: "column",
        minHeight: 0, overflowY: "auto", boxSizing: "border-box",
      }}
    >
      {doc ? (() => {
        const fmt = fileFormat(doc.file_name);
        const page = pageOf(doc);
        const concepts = doc.concept_notes || [];
        return (
          <>
            <div style={{ position: "absolute", top: 16, right: 16, zIndex: 5 }}>
              <button
                type="button"
                data-testid="library-doc-menu"
                className={styles.dotsBtn}
                onClick={() => { setMenuOpen(!menuOpen); setConfirmDel(false); }}
                aria-label="Document actions"
                aria-expanded={menuOpen}
                style={{
                  width: 36, height: 36, display: "grid", placeItems: "center", border: 0, borderRadius: 9,
                  background: menuOpen ? "#EAE5DA" : "transparent", color: "#3F3B31", fontSize: 20, lineHeight: 1,
                  letterSpacing: 1, cursor: "pointer",
                }}
              >
                ···
              </button>
              {menuOpen && (
                <>
                  <div onClick={closeMenu} style={{ position: "fixed", inset: 0, zIndex: 30 }} />
                  <div role="menu" style={{ ...menuPanel, position: "absolute", right: 0, top: 42, zIndex: 31, width: 260, maxHeight: 620, overflowY: "auto" }}>
                    <button role="menuitem" className={styles.menuItem} style={menuItemStyle} onClick={() => { closeMenu(); onStartRename(); }}>Rename</button>
                    {folderOptions.length > 0 && (
                      <>
                        <span style={{ height: 1, margin: "4px 6px", background: "rgba(42,39,31,0.10)" }} />
                        <span style={menuHeading}>Add to Folder</span>
                        {folderOptions.map((o) => (
                          <button
                            key={o.id}
                            role="menuitemradio"
                            aria-checked={o.on}
                            className={styles.menuItem}
                            style={{ ...menuItemStyle, padding: "8px 10px", fontWeight: 400 }}
                            onClick={() => { closeMenu(); onToggleFolder(o.id); }}
                          >
                            <FolderIcon size={14} />
                            <span style={{ flex: 1 }}>{o.name}</span>
                            <span style={{ opacity: o.on ? 1 : 0, display: "inline-flex" }}><Tinted name="check" size={12} color="#445D22" /></span>
                          </button>
                        ))}
                      </>
                    )}
                    <span style={{ height: 1, margin: "4px 6px", background: "rgba(42,39,31,0.10)" }} />
                    <button
                      role="menuitem"
                      data-testid="library-doc-delete"
                      className={styles.dangerItem}
                      style={{ ...menuItemStyle, fontWeight: 700, color: "#A8443F", background: confirmDel ? "#F6E3E1" : "transparent" }}
                      onClick={() => { if (confirmDel) { closeMenu(); onDelete(); } else setConfirmDel(true); }}
                    >
                      {confirmDel ? "Click Again to Delete" : "Delete Document"}
                    </button>
                  </div>
                </>
              )}
            </div>

            {renaming ? (
              <div style={{ marginRight: 40, display: "flex", flexDirection: "column", gap: 6 }}>
                <input
                  autoFocus
                  data-testid="library-rename-input"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onFocus={(e) => e.target.select()}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") e.currentTarget.blur();
                    if (e.key === "Escape") { cancelRef.current = true; e.currentTarget.blur(); }
                  }}
                  onBlur={() => {
                    const cancel = cancelRef.current; cancelRef.current = false;
                    onEndRename(cancel ? null : draft.trim() || null);
                  }}
                  aria-label="Document name"
                  style={{
                    height: 46, padding: "0 12px", border: "1.5px solid #597536", borderRadius: 10, background: "#FDFCF9",
                    fontFamily: "var(--font-serif)", fontSize: 24, fontWeight: 600, color: "#2F4417", outline: "none",
                  }}
                />
                <span style={{ fontSize: 13, color: "#6F6857" }}>Enter to save · Esc to cancel</span>
              </div>
            ) : (
              <h2
                onDoubleClick={onStartRename}
                title="Double-click to rename"
                style={{
                  margin: 0, paddingRight: 40, fontFamily: "var(--font-serif)", fontSize: 26, fontWeight: 600,
                  letterSpacing: "-0.015em", lineHeight: 1.15, color: "#2F4417", textWrap: "pretty", cursor: "text",
                }}
              >
                {displayTitle(doc.file_name)}
              </h2>
            )}

            <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 16, fontSize: 14, color: "#1A1814" }}>
              <span style={{
                height: 22, padding: "0 8px", borderRadius: 6, background: FMT_COLORS[fmt] || "#8A8372", color: "#FFFFFF",
                fontSize: 12, fontWeight: 700, letterSpacing: "0.04em", display: "inline-flex", alignItems: "center",
              }}>{fmt}</span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#6F6857" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="2" y="3" width="12" height="11" rx="2" /><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" /></svg>
                <span>Added <strong style={{ fontWeight: 700 }}>{addedLabel(doc.created_at)}</strong></span>
              </span>
            </div>
            <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
              <span style={chip}>
                <CourseDot color={course ? course.color : null} />
                {course ? (course.name ? `${course.code} · ${course.name}` : course.code) : "Uncategorized"}
              </span>
              {folderName && <span style={chip}><FolderIcon size={13} />{folderName}</span>}
            </div>

            {(page.lines.length > 0 || concepts.length > 0) && <PageCard h={page.h} lines={page.lines} />}

            <h3 style={{ margin: "26px 0 0", fontSize: 18, fontWeight: 700 }}>Summary</h3>
            <p style={{ margin: "6px 0 0", fontSize: 15, color: "#3F3B31", textWrap: "pretty" }}>
              {doc.summary || (doc.processed_at ? "No summary for this document." : "Sapling is still reading this document.")}
            </p>

            {concepts.length > 0 && (
              <>
                <div style={{ marginTop: 22, fontFamily: "var(--font-mono)", fontSize: 12, letterSpacing: "0.14em", textTransform: "uppercase", color: "#6F6857" }}>Linked Concepts</div>
                <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  {concepts.map((c, i) => (
                    <span key={`${c.name}-${i}`} style={{
                      display: "flex", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 38, padding: "0 10px",
                      borderRadius: 9, background: "#F6F3EC", fontSize: 14, fontWeight: 500, textAlign: "center",
                    }}>{c.name}</span>
                  ))}
                </div>
              </>
            )}

            <button
              type="button"
              data-testid="library-open"
              className={styles.openBtn}
              onClick={onOpen}
              style={{
                marginTop: 24, height: 50, border: 0, borderRadius: 12, background: "#445D22", color: "#FFFFFF",
                ...INHERIT_FONT, fontSize: 16, fontWeight: 700, cursor: "pointer", flexShrink: 0,
              }}
            >
              Open
            </button>
          </>
        );
      })() : (
        <div style={{ margin: "auto 0", textAlign: "center", color: "#3F3B31", padding: "24px 0" }}>
          <div style={{ fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 600, color: "#1A1814" }}>Nothing Selected</div>
          <div style={{ marginTop: 6, fontSize: 15 }}>Pick a document to see its summary and linked concepts.</div>
        </div>
      )}
    </aside>
  );
}

const chip: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 7, height: 28, padding: "0 11px", borderRadius: 14,
  background: "#FDFCF9", border: "1px solid rgba(42,39,31,0.12)", fontSize: 13, fontWeight: 600,
};
