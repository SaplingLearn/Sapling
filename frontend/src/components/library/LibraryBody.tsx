"use client";
/**
 * The Library's scrolling column: the load-error notice, the saved study
 * guides, the folders and documents in whichever view is on, and the empty
 * state.
 *
 * Split out of `Library.tsx` so that file stays wiring: this is the part that
 * branches on what there is to show.
 */
import React from "react";

import type { DocFolder, Document as Doc } from "@/lib/types";
import type { EnrolledCourse } from "@/lib/api";
import type { GuideCard } from "@/lib/studyGuide/types";
import { LibraryGuides } from "../studyGuide/home/LibraryGuides";

import { EmptyState } from "./LibraryBits";
import { DocRow, FolderRow, ListHeader } from "./LibraryList";
import { DocCard, FolderCard, PANEL_GRID } from "./LibraryPanel";
import type { DocRowProps } from "./LibraryList";
import type { FolderRowProps } from "./LibraryList";

export interface LibraryBodyProps {
  view: "list" | "panel";
  columns: string;
  showCourse: boolean;
  isTrash: boolean;

  documents: Doc[];
  folders: DocFolder[];
  /** Per-row props, already wired by the parent. */
  rowProps: (doc: Doc, index: number) => Omit<DocRowProps, "columns" | "showCourse">;
  folderProps: (folderId: string, index: number)
    => Omit<FolderRowProps, "columns" | "showCourse">;

  allChecked: boolean;
  onToggleAll: () => void;

  /** The documents read failed; `hasDocuments` says whether anything is shown. */
  loadError: boolean;
  hasDocuments: boolean;
  onRetry: () => void;

  guides: GuideCard[];
  guidesFailed: boolean;
  onGuidesRetry: () => void;
  courses: EnrolledCourse[];

  empty: boolean;
  /** Guides may still be on their way; "nothing here" waits for them. */
  guidesKnown: boolean;
  emptyTitle: string;
  emptyBody: string;
  hasQuery: boolean;
  scoped: boolean;
  onClearSearch: () => void;
  onSearchAll: () => void;

  onScroll: () => void;
}

function LoadError({
  hasDocuments, onRetry,
}: {
  hasDocuments: boolean;
  onRetry: () => void;
}) {
  if (hasDocuments) {
    return (
      <div data-testid="library-load-error" role="alert" style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 12,
        fontSize: 14, color: "#6F6857",
      }}>
        Couldn&apos;t refresh your library — showing what was last loaded.
        <button
          data-testid="library-load-retry"
          onClick={onRetry}
          style={{
            border: 0, padding: 0, background: "transparent", color: "#445D22",
            font: "inherit", fontWeight: 700, cursor: "pointer",
            textDecoration: "underline", textUnderlineOffset: 3,
          }}
        >Retry</button>
      </div>
    );
  }
  return (
    <div data-testid="library-load-error" role="alert" style={{
      maxWidth: 440, margin: "72px auto 0", textAlign: "center",
      display: "flex", flexDirection: "column", alignItems: "center", gap: 10,
    }}>
      <div style={{ fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 600 }}>
        Couldn&apos;t load your library
      </div>
      <div style={{ fontSize: 15, color: "#3F3B31" }}>
        Your documents are safe. Check your connection and try again.
      </div>
      <button
        data-testid="library-load-retry"
        className="sapHoverForest"
        onClick={onRetry}
        style={{
          marginTop: 6, height: 38, padding: "0 16px", border: 0, background: "#445D22",
          color: "#FFFFFF", borderRadius: 10, font: "inherit", fontSize: 14,
          fontWeight: 700, cursor: "pointer",
        }}
      >Try again</button>
    </div>
  );
}

export function LibraryBody(props: LibraryBodyProps) {
  const {
    view, columns, showCourse, isTrash, documents, folders, rowProps, folderProps,
    allChecked, onToggleAll, loadError, hasDocuments, onRetry, guides, guidesFailed,
    onGuidesRetry, courses, empty, guidesKnown, emptyTitle, emptyBody, hasQuery,
    scoped, onClearSearch, onSearchAll, onScroll,
  } = props;

  const showEmpty = empty && guidesKnown && !(loadError && !hasDocuments);

  return (
    <div
      onScroll={onScroll}
      style={{
        flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden",
        padding: "6px 6px 96px 0",
        animation: "sapFadeIn 260ms cubic-bezier(0.2, 0.7, 0.2, 1) 900ms both",
      }}
    >
      {loadError && <LoadError hasDocuments={hasDocuments} onRetry={onRetry} />}

      {!isTrash && (
        <LibraryGuides
          guides={guides}
          courses={courses}
          failed={guidesFailed}
          onRetry={onGuidesRetry}
        />
      )}

      {!empty && view === "list" && (
        <>
          <ListHeader
            columns={columns}
            showCourse={showCourse}
            allChecked={allChecked}
            onToggleAll={onToggleAll}
          />
          {folders.map((f, i) => (
            <FolderRow
              key={f.id}
              columns={columns}
              showCourse={showCourse}
              {...folderProps(f.id, i)}
            />
          ))}
          {documents.map((d, i) => (
            <DocRow key={d.id} columns={columns} showCourse={showCourse} {...rowProps(d, i)} />
          ))}
        </>
      )}

      {!empty && view === "panel" && (
        <div style={PANEL_GRID}>
          {folders.map((f, i) => <FolderCard key={f.id} {...folderProps(f.id, i)} />)}
          {documents.map((d, i) => (
            <DocCard key={d.id} showCourseDot={showCourse} {...rowProps(d, i)} />
          ))}
        </div>
      )}

      {showEmpty && (
        <EmptyState
          title={emptyTitle}
          body={emptyBody}
          hasQuery={hasQuery}
          scoped={scoped}
          onClearSearch={onClearSearch}
          onSearchAll={onSearchAll}
        />
      )}
    </div>
  );
}
