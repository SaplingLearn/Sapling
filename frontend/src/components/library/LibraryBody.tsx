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

import { EmptyState } from "./LibraryBits";
import { DocRow, FolderRow, ListHeader } from "./LibraryList";
import { DocCard, FolderCard, PANEL_GRID } from "./LibraryPanel";
import type { DocRowProps } from "./LibraryList";
import type { FolderRowProps } from "./LibraryList";

export interface LibraryBodyProps {
  view: "list" | "panel";
  columns: string;
  showCourse: boolean;

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


  empty: boolean;
  emptyTitle: string;
  emptyBody: string;
  hasQuery: boolean;
  scoped: boolean;
  onClearSearch: () => void;
  onSearchAll: () => void;

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

/** How long the two views are on screen together. Matches the keyframes. */
const SLIDE_MS = 300;
const SLIDE_EASE = "cubic-bezier(0.2, 0.7, 0.2, 1)";

/**
 * One half of the switch.
 *
 * Panel is the right-hand tab, so it arrives from the right and leaves to the
 * right; List does the mirror. Both halves are laid in the SAME grid cell so
 * they overlap for the length of one slide — the new view arrives while the
 * old one is still leaving, rather than appearing into the gap the old one
 * left behind.
 */
const slide = (view: "list" | "panel", dir: "in" | "out"): React.CSSProperties => ({
  gridArea: "1 / 1",
  animation: `sapView${dir === "in" ? "In" : "Out"}`
    + `${view === "panel" ? "Right" : "Left"} ${SLIDE_MS}ms ${SLIDE_EASE} both`,
  // The travel would otherwise widen the page mid-flight.
  overflowX: "clip",
  ...(dir === "out" ? { pointerEvents: "none" as const } : null),
});

/**
 * The view that is still leaving, for one slide's length.
 *
 * `null` whenever nothing is in flight, so the common case renders exactly one
 * child and the stack collapses to it.
 */
function useLeavingView(view: "list" | "panel"): "list" | "panel" | null {
  const [leaving, setLeaving] = React.useState<"list" | "panel" | null>(null);
  const previous = React.useRef(view);
  React.useEffect(() => {
    if (previous.current === view) return;
    setLeaving(previous.current);
    previous.current = view;
    const t = setTimeout(() => setLeaving(null), SLIDE_MS);
    return () => clearTimeout(t);
  }, [view]);
  return leaving;
}

export function LibraryBody(props: LibraryBodyProps) {
  const {
    view, columns, showCourse, documents, folders, rowProps, folderProps,
    allChecked, onToggleAll, loadError, hasDocuments, onRetry,
    empty, emptyTitle, emptyBody, hasQuery,
    scoped, onClearSearch, onSearchAll,
  } = props;

  const showEmpty = empty && !(loadError && !hasDocuments);
  const leaving = useLeavingView(view);

  const renderView = (which: "list" | "panel", dir: "in" | "out") =>
    which === "list" ? (
      <div key={`list-${dir}`} style={slide("list", dir)} aria-hidden={dir === "out"}>
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
      </div>
    ) : (
      <div
        key={`panel-${dir}`}
        style={{ ...PANEL_GRID, ...slide("panel", dir) }}
        aria-hidden={dir === "out"}
      >
        {folders.map((f, i) => <FolderCard key={f.id} {...folderProps(f.id, i)} />)}
        {documents.map((d, i) => (
          <DocCard key={d.id} showCourseDot={showCourse} {...rowProps(d, i)} />
        ))}
      </div>
    );

  return (
    <div
      style={{
        // The PAGE scrolls, not this list: the title, search and scope bar
        // travel up with the documents rather than staying pinned.
        overflowX: "hidden",
        padding: "6px 6px 96px 0",
        animation: "sapFadeIn 260ms cubic-bezier(0.2, 0.7, 0.2, 1) 900ms both",
      }}
    >
      {loadError && <LoadError hasDocuments={hasDocuments} onRetry={onRetry} />}

      {/* The two views share one grid cell, so a switch overlaps them for one
          slide instead of blanking between them. `data-sliding` is only on the
          stack while both are present — it silences the per-row entrance, so
          the frame shows one panel moving rather than rows restaging. */}
      {!empty && (
        <div
          data-sliding={leaving ? "" : undefined}
          style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)" }}
        >
          {leaving && renderView(leaving, "out")}
          {renderView(view, "in")}
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
