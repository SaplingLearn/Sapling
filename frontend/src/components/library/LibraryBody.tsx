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
import { DocCard, FolderCard } from "./LibraryPanel";
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
      <div data-testid="library-load-error" role="alert" className="flex items-center gap-2 mb-3 text-base text-text-muted">
        Couldn&apos;t refresh your library — showing what was last loaded.
        <button
          data-testid="library-load-retry"
          onClick={onRetry}
          className="border-0 p-0 bg-transparent text-brand-forest [font-family:inherit] [font-size:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] font-bold cursor-pointer underline [text-underline-offset:3px]"
        >Retry</button>
      </div>
    );
  }
  return (
    <div data-testid="library-load-error" role="alert" className="max-w-110 mt-18 mx-auto mb-0 text-center flex flex-col items-center gap-2.5">
      <div className="font-serif text-2xl font-semibold">
        Couldn&apos;t load your library
      </div>
      <div className="text-[15px] text-ink-600">
        Your documents are safe. Check your connection and try again.
      </div>
      <button
        data-testid="library-load-retry"
        className="sapHoverForest mt-1.5 h-9.5 py-0 px-4 border-0 [background:#445D22] text-accent-fg rounded-md [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-bold cursor-pointer"
        onClick={onRetry}
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
        className="pt-4 grid grid-cols-[repeat(auto-fill,_minmax(250px,_1fr))] gap-6" style={{ ...slide("panel", dir) }}
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
      className="overflow-x-hidden pt-1.5 pr-1.5 pb-24 pl-0 [animation:sapFadeIn_260ms_cubic-bezier(0.2,_0.7,_0.2,_1)_900ms_both]"
    >
      {loadError && <LoadError hasDocuments={hasDocuments} onRetry={onRetry} />}

      {/* The two views share one grid cell, so a switch overlaps them for one
          slide instead of blanking between them. `data-sliding` is only on the
          stack while both are present — it silences the per-row entrance, so
          the frame shows one panel moving rather than rows restaging. */}
      {!empty && (
        <div
          data-sliding={leaving ? "" : undefined}
          className="grid grid-cols-[minmax(0,_1fr)]"
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
