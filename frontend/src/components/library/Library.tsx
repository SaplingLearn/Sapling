"use client";
/**
 * The Library, rebuilt from `designs/Sapling Library v2.dc.html`.
 *
 * Layout is the design's: a header, a filter row, and one scrolling column of
 * folders then documents, inside the repo's own shell and SideNav. The
 * prototype's right-hand preview panel is gone in v2 — a row's "⋯" dialog
 * holds what it used to, including the two controls the old Library kept
 * there (Type, and Scan to Knowledge Graph).
 *
 * This file is wiring. The parts live beside it: `libraryModel` (the filter →
 * sort pipeline), `rowModel` (what one row shows), `scopeText` (the words a
 * scope puts on screen), `useLibraryData` (reads, writes, undo),
 * `useLibraryUi` (selection, menus, drag, rename), `useLibraryScope` (what the
 * open scope resolves to), `useLibraryActions` (the verbs), `useRowProps` and
 * `useLibraryUpload`.
 */
import React from "react";
import { useRouter } from "next/navigation";

import { FullHeightScreen } from "../FullHeightScreen";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";

import { DocMenu } from "./DocMenu";
import { BulkBar, BulkBarReveal, UndoToast } from "./LibraryBits";
import { LibraryBody } from "./LibraryBody";
import { LibraryHeader } from "./LibraryHeader";
import { LibraryScopeBar } from "./LibraryScopeBar";
import { LibrarySkeleton } from "./LibrarySkeleton";
import { courseLabel, dedupeCourses, titleOf } from "./libraryModel";
import { scopeLabels, scopeOptions } from "./scopeText";
import { UploadWhereModal } from "./UploadWhereModal";
import { useLibraryActions } from "./useLibraryActions";
import { useLibraryData } from "./useLibraryData";
import { useLibraryKeys } from "./useLibraryKeys";
import { useLibraryScope } from "./useLibraryScope";
import { useLibraryUi } from "./useLibraryUi";
import { useLibraryUpload } from "./useLibraryUpload";
import { useRowProps } from "./useRowProps";

/**
 * How long the skeleton holds the page. The content underneath runs its own
 * entrance at 880–900 ms while the skeleton fades at 720 ms, so the two
 * overlap by design rather than being sequenced by a state change.
 */
const BOOT_MS = 980;

export function Library() {
  const router = useRouter();
  const toast = useToast();
  const { userId, userReady } = useUser();
  const data = useLibraryData(userId, userReady);
  const ui = useLibraryUi();

  const searchRef = React.useRef<HTMLInputElement>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const sectionRef = React.useRef<HTMLDivElement>(null);

  const [booted, setBooted] = React.useState(false);
  React.useEffect(() => {
    const t = setTimeout(() => setBooted(true), BOOT_MS);
    return () => clearTimeout(t);
  }, []);

  const courses = React.useMemo(() => dedupeCourses(data.courses), [data.courses]);
  const courseById = React.useMemo(
    () => new Map(courses.map(c => [c.course_id, c])), [courses],
  );

  const scope = useLibraryScope(
    ui, data.documents, data.trash, data.folders, courses, courseById,
  );

  const openDoc = React.useCallback(
    (docId: string) => router.push(`/library/${docId}/notes`), [router],
  );

  // Checking rows takes over from the single current row: it clears, so it
  // does not come back when the checks are cleared.
  const anyChecked = scope.checkedIds.length > 0;
  const { setSelected, setSelectedFolder } = ui;
  React.useEffect(() => {
    if (!anyChecked) return;
    setSelected(null);
    setSelectedFolder(null);
  }, [anyChecked, setSelected, setSelectedFolder]);

  const act = useLibraryActions({
    data, ui, userId, toast, courseById,
    folders: data.folders,
    scopeCourseId: scope.scopeCourseId,
    openFolder: scope.openFolder,
  });

  const { rowProps, folderProps } = useRowProps({
    ui, act,
    documents: data.documents,
    folders: data.folders,
    courseById,
    checkedIds: scope.checkedIds,
    q: scope.q,
    showCourse: scope.showCourse,
    isTrash: scope.isTrash,
    sectionRef,
    openDoc,
  });

  const notifySyllabus = React.useCallback(
    () => toast.info("Syllabus processed — new assignments will appear on the calendar."),
    [toast],
  );
  const upload = useLibraryUpload({
    userId, data, courses,
    scopeCourseId: scope.scopeCourseId,
    openFolderId: scope.openFolder?.id ?? null,
    goTo: ui.setLoc,
    select: ui.setSelected,
    notifySyllabus,
  });

  useLibraryKeys({
    ids: React.useMemo(() => scope.rows.map(d => d.id), [scope.rows]),
    searchRef,
    setSelected: ui.setSelected,
  });

  const labels = scopeLabels({
    loc: ui.loc, query: ui.query, type: ui.type,
    course: scope.scopeCourse, folderName: scope.openFolder?.name,
  });
  const options = React.useMemo(() => scopeOptions({
    documents: data.documents, courses, loc: ui.loc,
    scopeCourseId: scope.scopeCourseId, trashCount: data.trash.length, go: ui.setLoc,
  }), [data.documents, courses, ui.loc, scope.scopeCourseId, data.trash.length, ui.setLoc]);

  const empty = scope.rows.length + scope.folderItems.length === 0;
  const menuDoc = ui.docMenu
    ? scope.source.find(d => d.id === ui.docMenu!.docId)
    : undefined;

  return (
    <FullHeightScreen>
      <main
        // Scopes the design's custom scrollbar and its reduced-motion override
        // to this screen; see library-notes.css.
        data-sap-surface=""
        onDragOver={e => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); }}
        onDrop={e => {
          const files = [...(e.dataTransfer.files || [])];
          if (!files.length) return;
          e.preventDefault();
          upload.pickFiles(files);
        }}
        onScroll={() => { if (ui.docMenu) ui.closeAllMenus(); }}
        style={{
          position: "relative", flex: 1, minWidth: 0, display: "grid",
          gridTemplateColumns: "minmax(0, 1fr)", gridTemplateRows: "auto auto",
          alignContent: "start", overflowY: "auto", overflowX: "hidden",
          padding: "0 64px 0 56px", boxSizing: "border-box",
          background: "#FAF8F3", color: "#1A1814", fontSize: 15, lineHeight: 1.45,
          WebkitFontSmoothing: "antialiased",
        }}
      >
        {!booted && <LibrarySkeleton view={ui.view} />}

        {/**
          * The title, search, scope and view toggle, as one block that
          * SCROLLS with the page and then stays. It is not pinned from the
          * start: the row travels up with the documents, and once it reaches
          * the top it holds there so the search and the buttons stay usable
          * however far down the list you are.
          *
          * The scope bar moved in here from the documents section so the two
          * stick together, and its `border-bottom` is the block's own bottom
          * edge — the divider IS where this section ends.
          *
          * The page keeps the horizontal padding; the 36px top is this
          * block's, so the air above the title comes WITH it when it sticks
          * and the background covers the rows passing underneath.
          */}
        <div style={{
          gridColumn: 1, gridRow: 1,
          position: "sticky", top: 0, zIndex: 25,
          background: "#FAF8F3", paddingTop: 36,
        }}>
          <LibraryHeader
            query={ui.query}
            onQuery={ui.setQuery}
            searchRef={searchRef}
            fileRef={fileRef}
            onFiles={upload.pickFiles}
            onNewDocument={act.newDocument}
            onNewFolder={act.newFolder}
            sort={ui.sortKey}
            onSort={ui.setSortKey}
            type={ui.type}
            onType={ui.setType}
            typeCounts={scope.typeCounts}
            scopedCount={scope.scoped.length}
            menu={ui.headerMenu}
            onMenu={ui.openHeaderMenu}
            menuClosing={ui.closing}
            canUpload={courses.length > 0}
          />
            <LibraryScopeBar
              isTrash={scope.isTrash}
              title={labels.title}
              dotColor={scope.scopeCourse?.color ?? null}
              showDot={scope.kind !== "all" && !scope.isTrash}
              courseMenuOpen={ui.courseMenu}
              onCourseMenu={ui.openCourseMenu}
              menuClosing={ui.closing}
              scopeOptions={options}
              isFolder={scope.kind === "f"}
              folderRenaming={ui.edit?.kind === "folder" && ui.edit.id === scope.openFolder?.id}
              folderDraft={ui.edit ? ui.edit.draft : ""}
              onFolderDraft={ui.setDraft}
              onFolderRenameStart={() => {
                const f = scope.openFolder;
                if (f) ui.startEdit(f.id, "folder", f.name);
              }}
              onFolderRenameCommit={act.commitEdit}
              onFolderRenameCancel={ui.cancelEdit}
              onFolderDelete={act.deleteOpenFolder}
              trashHasItems={scope.isTrash && data.trash.length > 0}
              emptyConfirm={ui.emptyConfirm}
              onEmptyTrash={() => {
                if (!ui.emptyConfirm) { ui.setEmptyConfirm(true); return; }
                act.purgeDocs(data.trash.map(d => d.id));
              }}
              scoped={scope.searchScoped}
              scopeName={labels.name}
              onSearchAll={() => ui.setLoc("all")}
              courseScanLabel={scope.scopeCourse ? courseLabel(scope.scopeCourse) : null}
              courseScanning={act.courseScanning}
              onCourseScan={() => {
                const id = scope.scopeCourseId;
                if (id) act.runCourseScan(id);
              }}
              view={ui.view}
              onView={ui.setView}
            />
        </div>


        <section
          ref={sectionRef}
          aria-label="Documents"
          style={{
            gridColumn: 1, gridRow: 2, position: "relative", display: "flex",
            flexDirection: "column", minWidth: 0,
          }}
        >

          {/* Mounted through its exit: it animates in and out, and the list
              below glides with it (see BulkBarReveal). */}
          <BulkBarReveal open={scope.checkedIds.length > 0}>
            <BulkBar
              count={scope.checkedIds.length}
              isTrash={scope.isTrash}
              menuOpen={ui.bulkMenu}
              menuClosing={ui.closing}
              onMenu={ui.openBulkMenu}
              courses={courses}
              folders={data.folders}
              onMoveCourse={id => {
                ui.closeAllMenus();
                act.moveToCourse(scope.checkedIds, id);
              }}
              onMoveFolder={id => {
                ui.closeAllMenus();
                act.moveToFolder(scope.checkedIds, id);
              }}
              onRestore={() => act.restoreDocs(scope.checkedIds)}
              onDelete={() => {
                if (!scope.isTrash) { act.trashDocs(scope.checkedIds); return; }
                if (!ui.bulkConfirm) { ui.setBulkConfirm(true); return; }
                act.purgeDocs(scope.checkedIds);
              }}
              deleteConfirm={ui.bulkConfirm}
              onClear={() => { ui.closeAllMenus(); ui.clearChecked(); setSelected(null); }}
            />
          </BulkBarReveal>

          <LibraryBody
            view={ui.view}
            columns={scope.columns}
            showCourse={scope.showCourse}
            documents={scope.rows}
            folders={scope.folderItems}
            rowProps={rowProps}
            folderProps={folderProps}
            allChecked={scope.allChecked}
            onToggleAll={() => ui.setChecked(
              scope.allChecked ? {} : Object.fromEntries(scope.rows.map(d => [d.id, true])),
            )}
            loadError={data.loadError}
            hasDocuments={data.documents.length > 0}
            onRetry={data.retry}
            empty={empty}
            emptyTitle={labels.emptyTitle}
            emptyBody={labels.emptyBody}
            hasQuery={ui.query.length > 0}
            scoped={scope.searchScoped}
            onClearSearch={() => ui.setQuery("")}
            onSearchAll={() => ui.setLoc("all")}
          />

          {data.toast && (
            <UndoToast
              message={data.toast.msg}
              onUndo={data.toast.undo ? () => { void data.toast!.undo!(); } : undefined}
            />
          )}

          {ui.docMenu && menuDoc && (
            <DocMenu
              doc={menuDoc}
              position={ui.docMenu.position}
              closing={ui.closing}
              courses={courses}
              folders={data.folders}
              sub={ui.docMenu.sub}
              onSub={ui.setDocMenuSub}
              onClose={ui.closeAllMenus}
              onOpen={() => { ui.closeAllMenus(); openDoc(menuDoc.id); }}
              onRename={() => {
                ui.closeAllMenus();
                ui.startEdit(menuDoc.id, "doc", titleOf(menuDoc));
              }}
              // The uploaded file is not kept after processing, so there is no
              // original to hand back — the notes page is what can be exported.
              onDownload={() => { ui.closeAllMenus(); openDoc(menuDoc.id); }}
              onMoveCourse={id => { ui.closeAllMenus(); act.moveToCourse([menuDoc.id], id); }}
              onMoveFolder={id => { ui.closeAllMenus(); act.moveToFolder([menuDoc.id], id); }}
              onType={c => { ui.closeAllMenus(); void data.setCategory(menuDoc.id, c); }}
              onScan={() => act.runScan(menuDoc.id)}
              scanState={act.scans[menuDoc.id] ?? "idle"}
              onTrash={() => act.trashDocs([menuDoc.id])}
            />
          )}
        </section>

        {upload.dialog && (
          <UploadWhereModal
            rows={upload.queue.rows}
            courses={courses}
            folders={data.folders}
            courseId={upload.dialog.courseId}
            onCourseId={upload.setCourseId}
            folderId={upload.dialog.folderId}
            onFolderId={upload.setFolderId}
            suggested={upload.dialog.suggested}
            started={upload.dialog.started}
            busy={upload.queue.busy}
            finished={upload.queue.finished}
            onConfirm={upload.confirm}
            onRetry={upload.retryRow}
            onCancelRow={upload.queue.cancel}
            onClose={upload.close}
            closing={upload.closing}
          />
        )}
      </main>
    </FullHeightScreen>
  );
}
