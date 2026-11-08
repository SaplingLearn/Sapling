"use client";
// Library: course/folder explorer for a student's uploaded documents.
// Spec: design handoff "Sapling Library.dc.html" (markup + Component logic).
import React from "react";
import { useRouter } from "next/navigation";
import { DocumentUploadModal } from "../DocumentUploadModal";
import { LibraryGridSkeleton, LibraryListSkeleton } from "../Skeleton";
import { useToast } from "../ToastProvider";
import { useIsMobile } from "@/lib/useIsMobile";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { useVisibleNavSections } from "@/lib/useNavSections";
import { useUser } from "@/context/UserContext";
import { getDocuments, deleteDocument, getCourses, createNote, type EnrolledCourse } from "@/lib/api";
import {
  getLibraryFolders, createLibraryFolder, renameLibraryFolder, deleteLibraryFolder,
  moveDocumentsToFolder, renameLibraryDocument, type LibraryFolder,
} from "@/lib/libraryApi";
import type { Document as Doc } from "@/lib/types";
import styles from "../library/Library.module.css";
import {
  FMT_COLORS, SORTS, TYPES, TYPE_CHIPS, addedLabel, dedupeCourses, displayTitle, fileFormat, highlight,
  matchesQuery, pageOf, sortDocs, typeOf, uniqueName, type Category, type CourseInfo, type SortKey,
} from "../library/model";
import {
  CheckBox, CourseDot, FolderIcon, PageCard, Tinted, menuHeading, menuItemStyle, menuPanel, renameInput,
} from "../library/parts";
import { LibraryPreview } from "../library/LibraryPreview";
import { LibraryReader } from "../library/LibraryReader";
import { INHERIT_FONT } from "@/lib/inheritFont";

type Loc = "all" | `c:${string}` | `f:${string}`;
type Menu = "new" | "sort" | "bulk" | null;
type Edit = { id: string; kind: "folder" | "doc"; draft: string } | null;
type Toast = { msg: string; undo?: () => void } | null;

const TMP = "tmp-";
const TOAST_MS = 5000;

function errText(err: unknown): string {
  const e = err as { detail?: string; message?: string } | null;
  return String(e?.detail || e?.message || err);
}

function markScrolling(e: React.UIEvent<HTMLElement>) {
  const el = e.currentTarget as HTMLElement & { __sbT?: number };
  el.setAttribute("data-scrolling", "");
  window.clearTimeout(el.__sbT);
  el.__sbT = window.setTimeout(() => el.removeAttribute("data-scrolling"), 900);
}

export function Library() {
  const toast = useToast();
  const isMobile = useIsMobile();
  const router = useRouter();
  const { userId, userReady } = useUser();
  const navSections = useVisibleNavSections();
  const notesVisible = navSections.some((s) => s.items.some((i) => i.href === "/notetaker"));

  const [documents, setDocuments] = React.useState<Doc[]>([]);
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [folders, setFolders] = React.useState<LibraryFolder[]>([]);
  const [placements, setPlacements] = React.useState<Record<string, string>>({});
  const [loading, setLoading] = React.useState(true);
  // A failed load is NOT an empty library (#769).
  const [loadError, setLoadError] = React.useState(false);
  const loadReq = useLatestRequest();

  const [loc, setLoc] = React.useState<Loc>("all");
  const [type, setType] = React.useState<Category | "all">("all");
  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState<SortKey>("recent");
  const [view, setView] = React.useState<"list" | "panel">("list");
  const [sel, setSel] = React.useState<string | null>(null);
  const [checked, setChecked] = React.useState<Record<string, boolean>>({});
  const [menu, setMenu] = React.useState<Menu>(null);
  const [bulkConfirm, setBulkConfirm] = React.useState(false);
  const [renaming, setRenaming] = React.useState(false);
  const [edit, setEdit] = React.useState<Edit>(null);
  const [pendingDoc, setPendingDoc] = React.useState<{ id: string; courseId: string } | null>(null);
  const [fRenaming, setFRenaming] = React.useState(false);
  const [fDraft, setFDraft] = React.useState("");
  const [dropOn, setDropOn] = React.useState<string | null>(null);
  const [dragging, setDragging] = React.useState<string[]>([]);
  const [hiddenDocs, setHiddenDocs] = React.useState<Set<string>>(new Set());
  const [hiddenFolders, setHiddenFolders] = React.useState<Set<string>>(new Set());
  const [toastState, setToastState] = React.useState<Toast>(null);
  const [focus, setFocus] = React.useState(false);
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [reading, setReading] = React.useState<Doc | null>(null);

  const searchRef = React.useRef<HTMLInputElement>(null);
  const dragIds = React.useRef<string[]>([]);
  const toastTimer = React.useRef<number | undefined>(undefined);
  // A deferred delete runs when its undo toast expires or is replaced.
  const pendingCommit = React.useRef<(() => void) | null>(null);
  const lastIds = React.useRef<string[]>([]);

  // ── Load ────────────────────────────────────────────────────────────────
  const load = React.useCallback(async () => {
    if (!userId) return;
    const run = loadReq.begin();
    try {
      const [docs, crs, lib] = await Promise.all([
        getDocuments(userId),
        getCourses(userId),
        // Folders are an organisation layer: if they fail, documents still load.
        getLibraryFolders().catch((err) => { console.error("library folders load failed", err); return null; }),
      ]);
      if (!run.isCurrent()) return;
      setDocuments((docs.documents || []) as Doc[]);
      setCourses(crs.courses || []);
      if (lib) { setFolders(lib.folders || []); setPlacements(lib.placements || {}); }
      setLoadError(false);
    } catch (err) {
      if (!run.isCurrent()) return;
      console.error("library load failed", err);
      setLoadError(true);
    } finally {
      if (run.isCurrent()) setLoading(false);
    }
  }, [userId, loadReq]);

  React.useEffect(() => { if (userReady && userId) load(); }, [userReady, userId, load]);

  const retryLoad = () => { setLoading(true); load(); };

  // ── Toast with undo ─────────────────────────────────────────────────────
  const flushCommit = React.useCallback(() => {
    const c = pendingCommit.current;
    pendingCommit.current = null;
    if (c) c();
  }, []);

  const flash = React.useCallback((msg: string, undo?: () => void, commit?: () => void) => {
    flushCommit();
    window.clearTimeout(toastTimer.current);
    pendingCommit.current = commit || null;
    setToastState({ msg, undo });
    toastTimer.current = window.setTimeout(() => { flushCommit(); setToastState(null); }, TOAST_MS);
  }, [flushCommit]);

  const undo = () => {
    window.clearTimeout(toastTimer.current);
    const u = toastState?.undo;
    pendingCommit.current = null;
    setToastState(null);
    if (u) u();
  };

  React.useEffect(() => () => { window.clearTimeout(toastTimer.current); flushCommit(); }, [flushCommit]);

  // ── Derived data ────────────────────────────────────────────────────────
  const courseList = React.useMemo(() => dedupeCourses(courses), [courses]);
  const courseById = React.useMemo(() => new Map(courseList.map((c) => [c.id, c])), [courseList]);
  const liveDocs = React.useMemo(() => documents.filter((d) => !hiddenDocs.has(d.id)), [documents, hiddenDocs]);
  const liveFolders = React.useMemo(() => folders.filter((f) => !hiddenFolders.has(f.id)), [folders, hiddenFolders]);
  const folderById = React.useMemo(() => new Map(liveFolders.map((f) => [f.id, f])), [liveFolders]);
  const folderOf = React.useCallback(
    (d: Doc) => { const f = placements[d.id]; return f && folderById.has(f) ? f : null; },
    [placements, folderById],
  );
  const courseOf = (d: Doc): CourseInfo | null => (d.course_id ? courseById.get(d.course_id) ?? null : null);
  const courseCode = (id: string | null) => (id ? courseById.get(id)?.code ?? "Course" : "Uncategorized");

  const q = query.trim().toLowerCase();
  const [lk, lid]: [string, string | null] = loc === "all" ? ["all", null] : [loc.slice(0, 1), loc.slice(2)];
  const courseRoot = lk === "c" && !q;
  const curFolder = lk === "f" ? folderById.get(lid!) ?? null : null;
  const locCourseId: string | null = lk === "c" ? (lid === "none" ? null : lid) : curFolder ? curFolder.course_id : null;

  const inLoc = (d: Doc) => {
    if (lk === "all") return true;
    if (lk === "c") return (lid === "none" ? !d.course_id : d.course_id === lid) && (!courseRoot || !folderOf(d));
    return folderOf(d) === lid;
  };
  const base = liveDocs.filter((d) => inLoc(d) && matchesQuery(d, q, courseOf(d) ?? undefined));
  const list = sortDocs(base.filter((d) => type === "all" || d.category === type), sort, (d) => courseOf(d)?.code ?? "");
  lastIds.current = list.map((d) => d.id);
  const checkedIds = Object.keys(checked).filter((k) => checked[k] && liveDocs.some((d) => d.id === k));
  const pv = list.find((d) => d.id === sel) || (sel ? liveDocs.find((d) => d.id === sel && inLoc(d)) : null) || list[0] || null;
  const folderItems = courseRoot ? liveFolders.filter((f) => f.course_id === (lid === "none" ? null : lid)) : [];
  const empty = list.length === 0 && folderItems.length === 0 && !pendingDoc;
  const scopeName = lk === "all" ? "" : lk === "c" ? (lid === "none" ? "Uncategorized" : courseCode(lid)) : curFolder?.name ?? "";

  // ── Keyboard: "/" focuses search, arrows move the selection ─────────────
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const tag = (t?.tagName || "").toLowerCase();
      const typing = tag === "input" || tag === "select" || tag === "textarea" || !!t?.isContentEditable;
      if (e.key === "/" && !typing) { e.preventDefault(); searchRef.current?.focus(); return; }
      if ((e.key === "ArrowDown" || e.key === "ArrowUp") && (!typing || t === searchRef.current)) {
        const ids = lastIds.current;
        if (!ids.length) return;
        e.preventDefault();
        setSel((cur) => {
          const i = cur ? ids.indexOf(cur) : -1;
          const n = e.key === "ArrowDown" ? Math.min(ids.length - 1, i + 1) : Math.max(0, i - 1);
          return ids[n < 0 ? 0 : n];
        });
        setRenaming(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ── Actions ─────────────────────────────────────────────────────────────
  const docTitle = (id: string) => displayTitle(documents.find((d) => d.id === id)?.file_name || "");
  const nameFor = (ids: string[]) => (ids.length === 1 ? `“${docTitle(ids[0])}”` : `${ids.length} documents`);

  const applyPlacements = (ids: string[], target: (id: string) => string | null) =>
    setPlacements((p) => {
      const next = { ...p };
      for (const id of ids) { const f = target(id); if (f) next[id] = f; else delete next[id]; }
      return next;
    });

  /** Put documents in a folder (or take them out). Same-course only. */
  const move = async (ids: string[], folderId: string | null) => {
    if (!ids.length) return;
    const folder = folderId ? folderById.get(folderId) : null;
    if (folder && ids.some((id) => (documents.find((d) => d.id === id)?.course_id ?? null) !== folder.course_id)) {
      toast.info("A document can only go in a folder in its own course.");
      return;
    }
    const prev: Record<string, string | null> = Object.fromEntries(ids.map((id) => [id, placements[id] ?? null]));
    applyPlacements(ids, () => folderId);
    setChecked({}); setMenu(null); setDropOn(null); setBulkConfirm(false);
    try {
      await moveDocumentsToFolder(ids, folderId);
    } catch (err) {
      applyPlacements(ids, (id) => prev[id]);
      toast.error(`Move failed: ${errText(err)}`);
      return;
    }
    const label = folder ? `${courseCode(folder.course_id)} / ${folder.name}` : "";
    flash(folder ? `Moved ${nameFor(ids)} to ${label}` : `Removed ${nameFor(ids)} from its folder`, () => {
      applyPlacements(ids, (id) => prev[id]);
      const groups = new Map<string | null, string[]>();
      for (const id of ids) groups.set(prev[id], [...(groups.get(prev[id]) || []), id]);
      groups.forEach((g, f) => moveDocumentsToFolder(g, f).catch((err) => toast.error(`Undo failed: ${errText(err)}`)));
    });
  };

  /** Drop on a course row: take same-course documents out of their folder. */
  const dropOnCourse = (ids: string[], courseId: string | null) => {
    const same = ids.filter((id) => (documents.find((d) => d.id === id)?.course_id ?? null) === courseId);
    if (same.length < ids.length) toast.info("Documents stay in the course they were uploaded to.");
    const inFolders = same.filter((id) => placements[id]);
    if (inFolders.length) move(inFolders, null);
    else setDropOn(null);
  };

  /** Delete with undo: hidden now, deleted when the toast runs out. */
  const remove = (ids: string[]) => {
    setHiddenDocs((h) => new Set([...h, ...ids]));
    setChecked({}); setMenu(null); setBulkConfirm(false); setRenaming(false);
    if (sel && ids.includes(sel)) setSel(null);
    const unhide = () => setHiddenDocs((h) => { const n = new Set(h); ids.forEach((i) => n.delete(i)); return n; });
    flash(ids.length === 1 ? "Document deleted" : `${ids.length} documents deleted`, unhide, () => {
      Promise.allSettled(ids.map((id) => deleteDocument(id, userId || undefined))).then((res) => {
        const failed = ids.filter((_, i) => res[i].status === "rejected");
        setDocuments((ds) => ds.filter((d) => !ids.includes(d.id) || failed.includes(d.id)));
        setHiddenDocs((h) => { const n = new Set(h); ids.forEach((i) => n.delete(i)); return n; });
        if (failed.length) toast.error(`Couldn't delete ${failed.length === 1 ? "a document" : `${failed.length} documents`}. It's back in your library.`);
      });
    });
  };

  const deleteFolder = () => {
    if (!curFolder) return;
    const f = curFolder;
    setHiddenFolders((h) => new Set([...h, f.id]));
    setLoc(`c:${f.course_id || "none"}`);
    setFRenaming(false);
    const unhide = () => setHiddenFolders((h) => { const n = new Set(h); n.delete(f.id); return n; });
    flash(`Deleted folder “${f.name}”. Its documents are still in the course.`, () => { unhide(); setLoc(`f:${f.id}`); }, () => {
      deleteLibraryFolder(f.id).then(() => {
        setFolders((fs) => fs.filter((x) => x.id !== f.id));
        setPlacements((p) => Object.fromEntries(Object.entries(p).filter(([, v]) => v !== f.id)));
        unhide();
      }).catch((err) => { unhide(); toast.error(`Couldn't delete the folder: ${errText(err)}`); });
    });
  };

  const commitFolderRename = async () => {
    setFRenaming(false);
    const name = fDraft.trim();
    if (!curFolder || !name || name === curFolder.name) return;
    const id = curFolder.id, old = curFolder.name;
    setFolders((fs) => fs.map((x) => (x.id === id ? { ...x, name } : x)));
    try { await renameLibraryFolder(id, name); } catch (err) {
      setFolders((fs) => fs.map((x) => (x.id === id ? { ...x, name: old } : x)));
      toast.error(`Rename failed: ${errText(err)}`);
    }
  };

  const endDocRename = async (name: string | null) => {
    setRenaming(false);
    if (!pv || !name || name === displayTitle(pv.file_name)) return;
    const id = pv.id, old = pv.file_name;
    const ext = /\.[a-z0-9]+$/i.exec(old)?.[0] ?? "";
    setDocuments((ds) => ds.map((d) => (d.id === id ? { ...d, file_name: name + ext } : d)));
    try {
      const res = await renameLibraryDocument(id, name);
      setDocuments((ds) => ds.map((d) => (d.id === id ? { ...d, file_name: res.file_name } : d)));
    } catch (err) {
      setDocuments((ds) => ds.map((d) => (d.id === id ? { ...d, file_name: old } : d)));
      toast.error(`Rename failed: ${errText(err)}`);
    }
  };

  const newFolder = () => {
    const course = locCourseId;
    const id = `${TMP}${Date.now()}`;
    const name = uniqueName("New Folder", liveFolders.map((f) => f.name));
    setFolders((fs) => [...fs, { id, name, course_id: course, created_at: new Date().toISOString() }]);
    setEdit({ id, kind: "folder", draft: name });
    setMenu(null); setQuery(""); setLoc(`c:${course || "none"}`);
  };

  // "New Document" makes a note (the one in-app way to write a document) and
  // opens it in the Notetaker. With the Notetaker hidden or no course to file
  // it under, it opens the upload dialog instead.
  const newDoc = () => {
    setMenu(null);
    const courseId = locCourseId || courseList[0]?.id;
    if (!notesVisible || !courseId || !userId) { setUploadOpen(true); return; }
    const id = `${TMP}doc-${Date.now()}`;
    setPendingDoc({ id, courseId });
    setEdit({ id, kind: "doc", draft: uniqueName("New Document", liveDocs.map((d) => displayTitle(d.file_name))) });
    setQuery(""); setType("all"); setSort("recent");
  };

  const commitEdit = async () => {
    const e = edit;
    if (!e) return;
    setEdit(null);
    if (e.kind === "folder") {
      const others = liveFolders.filter((f) => f.id !== e.id).map((f) => f.name);
      const name = e.draft.trim() || uniqueName("New Folder", others);
      if (e.id.startsWith(TMP)) {
        setFolders((fs) => fs.map((f) => (f.id === e.id ? { ...f, name } : f)));
        const course = folders.find((f) => f.id === e.id)?.course_id ?? null;
        try {
          const made = await createLibraryFolder(name, course);
          setFolders((fs) => fs.map((f) => (f.id === e.id ? made : f)));
          setLoc((l) => (l === `f:${e.id}` ? `f:${made.id}` : l));
        } catch (err) {
          setFolders((fs) => fs.filter((f) => f.id !== e.id));
          toast.error(`Couldn't create the folder: ${errText(err)}`);
        }
      } else {
        const old = folders.find((f) => f.id === e.id)?.name;
        if (old === name) return;
        setFolders((fs) => fs.map((f) => (f.id === e.id ? { ...f, name } : f)));
        renameLibraryFolder(e.id, name).catch((err) => toast.error(`Rename failed: ${errText(err)}`));
      }
      return;
    }
    const pd = pendingDoc;
    if (!pd || !userId) return;
    const name = e.draft.trim() || uniqueName("New Document", liveDocs.map((d) => displayTitle(d.file_name)));
    try {
      const note = await createNote(userId, pd.courseId, name);
      setPendingDoc(null);
      router.push(`/notetaker?note=${encodeURIComponent(note.id)}`);
    } catch (err) {
      setPendingDoc(null);
      toast.error(`Couldn't create the document: ${errText(err)}`);
    }
  };

  const pickLoc = (key: Loc) => { setLoc(key); setFRenaming(false); setChecked({}); };

  const dropProps = (key: string, onDrop: (ids: string[]) => void) => ({
    onDragOver: (e: React.DragEvent) => { e.preventDefault(); if (dropOn !== key) setDropOn(key); },
    onDragLeave: () => setDropOn(null),
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      const ids = dragIds.current; dragIds.current = []; setDragging([]);
      if (ids.length) onDrop(ids); else setDropOn(null);
    },
  });

  const locRowStyle = (key: string): React.CSSProperties => {
    const on = loc === key, dr = dropOn === key;
    return {
      background: dr ? "#DCE8CE" : on ? "#EBF0E1" : "transparent",
      boxShadow: dr ? "inset 0 0 0 1.5px #597536" : on ? "inset 0 0 0 1px rgba(68,93,34,0.22)" : "none",
      fontWeight: on ? 700 : 500,
    };
  };

  // ── Render helpers ──────────────────────────────────────────────────────
  const listCols = lk === "all" ? "24px minmax(0, 1fr) 112px 100px 56px" : "24px minmax(0, 1fr) 120px 64px";
  const allChecked = list.length > 0 && list.every((d) => checked[d.id]);
  const visibleCount = list.length;
  const locCount = q
    ? `${visibleCount} ${visibleCount === 1 ? "result" : "results"} for “${query.trim()}”`
    : (folderItems.length ? `${folderItems.length} ${folderItems.length === 1 ? "folder" : "folders"} · ` : "") +
      `${visibleCount} ${visibleCount === 1 ? "document" : "documents"}`;
  const locTitle = lk === "all" ? "All Documents"
    : lk === "c" ? (lid === "none" ? "Uncategorized" : (() => { const c = courseById.get(lid!); return c ? (c.name ? `${c.code} · ${c.name}` : c.code) : "Course"; })())
    : `${curFolder ? courseCode(curFolder.course_id) + " / " : ""}${scopeName}`;
  const locDot = lk === "all" ? undefined : locCourseId ? courseById.get(locCourseId)?.color ?? null : null;

  const bulkCourse = (() => {
    const cs = new Set(checkedIds.map((id) => documents.find((d) => d.id === id)?.course_id ?? null));
    return cs.size === 1 ? [...cs][0] : undefined;
  })();
  const bulkFolders = bulkCourse === undefined ? [] : liveFolders.filter((f) => f.course_id === bulkCourse && !f.id.startsWith(TMP));

  const editInput = (size = 16) => (
    <input
      autoFocus
      data-testid="library-new-name"
      value={edit?.draft ?? ""}
      onFocus={(e) => e.target.select()}
      onChange={(e) => setEdit((x) => (x ? { ...x, draft: e.target.value } : x))}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === "Escape") e.currentTarget.blur(); }}
      onBlur={commitEdit}
      onClick={(e) => e.stopPropagation()}
      aria-label="Name"
      style={{ ...renameInput, fontSize: size }}
    />
  );

  const typeChips = TYPE_CHIPS.map((k) => {
    const on = type === k;
    const n = k === "all" ? base.length : base.filter((d) => d.category === k).length;
    return (
      <button
        key={k}
        type="button"
        aria-pressed={on}
        data-testid={`library-type-${k}`}
        onClick={() => setType(k)}
        style={{
          display: "inline-flex", alignItems: "center", gap: 7, height: 34, padding: "0 14px",
          border: `1px solid ${on ? "#445D22" : "rgba(42,39,31,0.14)"}`, borderRadius: 17,
          background: on ? "#445D22" : "#FDFCF9", color: on ? "#FFFFFF" : "#1A1814",
          ...INHERIT_FONT, fontSize: 14, fontWeight: 600, cursor: "pointer",
        }}
      >
        {k !== "all" && <span style={{ width: 8, height: 8, borderRadius: 2, background: TYPES[k].color }} />}
        {k === "all" ? "All Types" : TYPES[k].label}
        <span style={{ fontWeight: 400, color: on ? "rgba(255,255,255,0.78)" : "#6F6857" }}>{n}</span>
      </button>
    );
  });

  const layoutTab = (v: "list" | "panel", label: string, icon: React.ReactNode) => (
    <button
      data-testid={`library-layout-${v}`}
      type="button"
      role="tab"
      aria-selected={view === v}
      onClick={() => setView(v)}
      style={{
        display: "inline-flex", alignItems: "center", gap: 7, border: 0, padding: "0 14px", borderRadius: 9,
        ...INHERIT_FONT, fontSize: 14, fontWeight: 600, cursor: "pointer",
        background: view === v ? "#FDFCF9" : "transparent", color: view === v ? "#1A1814" : "#6F6857",
        boxShadow: view === v ? "0 1px 2px rgba(25,37,11,0.10)" : "none",
      }}
    >
      {icon}{label}
    </button>
  );

  const rowProps = (d: Doc) => {
    const on = !!pv && pv.id === d.id;
    const ck = !!checked[d.id];
    return {
      on, ck,
      check: (e: React.MouseEvent) => { e.stopPropagation(); setChecked((c) => ({ ...c, [d.id]: !ck })); setBulkConfirm(false); },
      pick: () => { setSel(d.id); setRenaming(false); setMenu(null); if (isMobile) setReading(d); },
      rename: () => { setSel(d.id); setRenaming(true); setMenu(null); },
      dragStart: (e: React.DragEvent) => {
        const ids = ck && checkedIds.length ? checkedIds : [d.id];
        dragIds.current = ids; setDragging(ids);
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", d.id); } catch { /* jsdom */ }
      },
      dragEnd: () => { dragIds.current = []; setDragging([]); setDropOn(null); },
      op: dragging.includes(d.id) ? 0.45 : 1,
    };
  };

  const subLine = (d: Doc) => {
    if (!q) return { text: d.summary || (d.processed_at ? "" : "Processing…"), hit: false };
    const tm = displayTitle(d.file_name).toLowerCase().includes(q);
    const cm = !tm && (d.concept_notes || []).find((c) => c.name.toLowerCase().includes(q));
    if (cm) return { text: `Linked concept: ${cm.name}`, hit: true };
    if (!tm && (d.summary || "").toLowerCase().includes(q)) return { text: `In summary: ${d.summary}`, hit: true };
    return { text: d.summary || "", hit: false };
  };

  const titleOf = (d: Doc) => {
    const n = highlight(displayTitle(d.file_name), q);
    return <>{n.a}{n.m && <mark style={{ background: "#D9E7C4", color: "inherit", borderRadius: 3 }}>{n.m}</mark>}{n.b}</>;
  };

  const fmtTile = (fmt: string, title: string) => (
    <span title={title} style={{
      width: 30, height: 38, borderRadius: 5, background: FMT_COLORS[fmt] || "#8A8372", color: "#FFFFFF",
      display: "grid", placeItems: "end center", paddingBottom: 5, boxSizing: "border-box",
      fontFamily: "var(--font-mono)", fontSize: 8, letterSpacing: "0.04em", flexShrink: 0,
    }}>{fmt}</span>
  );

  const pendingCourse = pendingDoc ? courseById.get(pendingDoc.courseId) ?? null : null;

  // ── Markup ──────────────────────────────────────────────────────────────
  return (
    <div
      data-testid="library-screen"
      style={{
        height: "100%", display: "grid", boxSizing: "border-box", overflow: "hidden",
        gridTemplateColumns: isMobile ? "minmax(0, 1fr)" : "236px minmax(0, 1fr) 400px",
        gridTemplateRows: isMobile ? "auto auto minmax(0, 1fr)" : "auto minmax(0, 1fr)",
        columnGap: 40, padding: isMobile ? "20px 16px 0" : "36px 48px 0 56px",
        background: "#FAF8F3", color: "#1A1814", fontFamily: "var(--font-sans)", fontSize: 15, lineHeight: 1.45,
        WebkitFontSmoothing: "antialiased",
      }}
    >
      <header style={{ gridColumn: 1, gridRow: 1, display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 24, paddingBottom: 14 }}>
        <h1 style={{ margin: 0, fontFamily: "var(--font-serif)", fontSize: 34, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.15 }}>Library</h1>
      </header>

      {!isMobile && (
        <nav aria-label="Library locations" className={styles.scroll} onScroll={markScrolling}
          style={{ gridColumn: 1, gridRow: 2, display: "flex", flexDirection: "column", gap: 2, minHeight: 0, overflowY: "auto", paddingBottom: 28 }}>
          <button type="button" data-testid="library-course-filter-all" onClick={() => pickLoc("all")}
            style={{ ...locRowStyle("all"), display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "9px 12px", border: 0, borderRadius: 10, color: "#1A1814", ...INHERIT_FONT, fontSize: 15, fontWeight: locRowStyle("all").fontWeight, textAlign: "left", cursor: "pointer" }}>
            <Tinted name="file" size={16} color="#597536" />
            <span style={{ flex: 1 }}>All Documents</span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "#6F6857" }}>{liveDocs.length}</span>
          </button>

          <div style={{ margin: "20px 12px 6px", fontFamily: "var(--font-mono)", fontSize: 12, letterSpacing: "0.12em", textTransform: "uppercase", color: "#6F6857" }}>Courses</div>
          {[...courseList.map((c) => ({ key: `c:${c.id}` as Loc, id: c.id as string | null, label: c.code, sub: c.name, color: c.color as string | null })),
            { key: "c:none" as Loc, id: null, label: "Uncategorized", sub: "Needs a course", color: null }].map((c) => {
            const st = locRowStyle(c.key);
            const count = liveDocs.filter((d) => (d.course_id ?? null) === c.id).length;
            return (
              <React.Fragment key={c.key}>
                <button type="button" data-testid={`library-course-filter-${c.id ?? "uncategorized"}`} onClick={() => pickLoc(c.key)}
                  {...dropProps(c.key, (ids) => dropOnCourse(ids, c.id))}
                  style={{ ...st, display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "8px 12px", border: 0, borderRadius: 10, color: "#1A1814", ...INHERIT_FONT, textAlign: "left", cursor: "pointer" }}>
                  <CourseDot color={c.color} size={10} />
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: "block", fontSize: 15, fontWeight: st.fontWeight, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.label}</span>
                    {c.sub && <span style={{ display: "block", fontSize: 13, color: "#6F6857", fontWeight: 400, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.sub}</span>}
                  </span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "#6F6857", fontWeight: 400 }}>{count}</span>
                </button>
                {liveFolders.filter((f) => f.course_id === c.id).map((f) => {
                  const key = `f:${f.id}` as Loc;
                  const fs = locRowStyle(key);
                  return (
                    <button type="button" key={f.id} data-testid={`library-folder-${f.id}`} onClick={() => pickLoc(key)}
                      {...dropProps(key, (ids) => move(ids, f.id))}
                      style={{ ...fs, display: "flex", alignItems: "center", gap: 9, width: "calc(100% - 22px)", marginLeft: 22, padding: "7px 12px", border: 0, borderRadius: 9, color: "#1A1814", ...INHERIT_FONT, fontSize: 14, textAlign: "left", cursor: "pointer" }}>
                      <FolderIcon />
                      <span style={{ flex: 1, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{f.name}</span>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "#6F6857", fontWeight: 400 }}>{liveDocs.filter((d) => folderOf(d) === f.id).length}</span>
                    </button>
                  );
                })}
              </React.Fragment>
            );
          })}
        </nav>
      )}

      {/* Toolbar */}
      <div style={{ gridColumn: isMobile ? 1 : "2 / 4", gridRow: isMobile ? 2 : 1, alignSelf: "end", marginBottom: 14, display: "flex", alignItems: "center", gap: 12, flexWrap: isMobile ? "wrap" : "nowrap" }}>
        <div style={{ position: "relative", flexShrink: 0 }}>
          <button type="button" data-testid="library-new" className={styles.newBtn} onClick={() => setMenu(menu === "new" ? null : "new")} aria-haspopup="menu" aria-expanded={menu === "new"}
            style={{ display: "inline-flex", alignItems: "center", gap: 8, height: 48, padding: "0 16px", border: "1.5px solid #445D22", borderRadius: 12, background: "#FDFCF9", color: "#445D22", ...INHERIT_FONT, fontSize: 15, fontWeight: 700, cursor: "pointer" }}>
            <Tinted name="plus" size={14} color="currentColor" />New
          </button>
          {menu === "new" && (
            <>
              <div onClick={() => setMenu(null)} style={{ position: "fixed", inset: 0, zIndex: 30 }} />
              <div role="menu" style={{ ...menuPanel, position: "absolute", left: 0, top: 54, zIndex: 31, width: 200 }}>
                <button role="menuitem" data-testid="library-new-doc" className={styles.menuItem} style={menuItemStyle} onClick={newDoc}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#445D22" strokeWidth="1.8" strokeLinejoin="round" aria-hidden="true"><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4" /></svg>New Document
                </button>
                <button role="menuitem" data-testid="library-new-folder" className={styles.menuItem} style={menuItemStyle} onClick={newFolder}>
                  <FolderIcon size={16} strokeWidth={1.8} />New Folder
                </button>
              </div>
            </>
          )}
        </div>
        <label style={{ flex: 1, minWidth: isMobile ? "100%" : 0, order: isMobile ? 5 : 0, display: "flex", alignItems: "center", gap: 10, height: 48, padding: "0 8px 0 16px", border: "1px solid rgba(42,39,31,0.16)", borderRadius: 12, background: "#FDFCF9", boxShadow: focus ? "0 0 0 3px rgba(89,117,54,0.22)" : "none", cursor: "text", boxSizing: "border-box" }}>
          <Tinted name="search" size={18} color="#6F6857" />
          <input
            ref={searchRef}
            data-testid="library-search"
            className={styles.searchInput}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setFocus(true)}
            onBlur={() => setFocus(false)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setQuery("");
              if (e.key === "Enter" && list[0]) setSel((list.find((d) => d.id === sel) || list[0]).id);
            }}
            placeholder="Search titles, summaries, and concepts"
            aria-label="Search documents"
            style={{ flex: 1, minWidth: 0, height: "100%", border: 0, background: "transparent", ...INHERIT_FONT, fontSize: 16, color: "#1A1814", outline: "none" }}
          />
          {query ? (
            <button type="button" data-testid="library-search-clear" onClick={() => setQuery("")} aria-label="Clear search"
              style={{ width: 32, height: 32, display: "grid", placeItems: "center", border: 0, borderRadius: 8, background: "#F4F1EA", color: "#3F3B31", cursor: "pointer" }}>
              <Tinted name="x" size={12} color="currentColor" />
            </button>
          ) : (
            <span title="Press / to search" style={{ minWidth: 24, height: 24, display: "grid", placeItems: "center", marginRight: 4, border: "1px solid rgba(42,39,31,0.18)", borderRadius: 6, fontFamily: "var(--font-mono)", fontSize: 12, color: "#6F6857", boxSizing: "border-box" }}>/</span>
          )}
        </label>
        <div style={{ position: "relative", flexShrink: 0 }}>
          <button type="button" data-testid="library-sort" className={styles.sortBtn} onClick={() => setMenu(menu === "sort" ? null : "sort")} aria-haspopup="listbox" aria-expanded={menu === "sort"} aria-label="Sort documents"
            style={{ display: "inline-flex", alignItems: "center", gap: 8, height: 48, padding: "0 14px", border: "1px solid rgba(42,39,31,0.16)", borderRadius: 12, background: "#FDFCF9", ...INHERIT_FONT, fontSize: 14, color: "#6F6857", cursor: "pointer" }}>
            Sort<span style={{ fontSize: 15, fontWeight: 600, color: "#1A1814" }}>{SORTS.find((s) => s[0] === sort)![1]}</span>
            <Tinted name="chevron-down" size={11} color="#6F6857" />
          </button>
          {menu === "sort" && (
            <>
              <div onClick={() => setMenu(null)} style={{ position: "fixed", inset: 0, zIndex: 30 }} />
              <div role="listbox" aria-label="Sort by" style={{ ...menuPanel, position: "absolute", right: 0, top: 54, zIndex: 31, width: 220 }}>
                {SORTS.map(([k, label]) => (
                  <button key={k} data-testid={`library-sort-${k}`} role="option" aria-selected={sort === k} className={styles.menuItem} onClick={() => { setSort(k); setMenu(null); }}
                    style={{ ...menuItemStyle, background: sort === k ? "#F2F6EE" : "transparent" }}>
                    <span style={{ flex: 1 }}>{label}</span>
                    <span style={{ opacity: sort === k ? 1 : 0, display: "inline-flex" }}><Tinted name="check" size={12} color="#445D22" /></span>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
        <button type="button" data-testid="library-upload" className={styles.uploadBtn} onClick={() => setUploadOpen(true)} disabled={courses.length === 0}
          title={courses.length === 0 ? "Enroll in a course first" : "Upload documents"}
          style={{ display: "inline-flex", alignItems: "center", gap: 8, height: 48, padding: "0 20px", flexShrink: 0, border: 0, background: "#445D22", color: "#FFFFFF", borderRadius: 11, ...INHERIT_FONT, fontSize: 15, fontWeight: 700, cursor: "pointer" }}>
          <Tinted name="upload" size={16} color="currentColor" />Upload Documents
        </button>
      </div>

      {/* Documents */}
      <section aria-label="Documents" style={{ gridColumn: isMobile ? 1 : 2, gridRow: isMobile ? 3 : 2, position: "relative", display: "flex", flexDirection: "column", minHeight: 0, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
          <div role="group" aria-label="Filter by type" style={{ flex: 1, minWidth: 0, display: "flex", gap: 8, flexWrap: "wrap" }}>{typeChips}</div>
          <div role="tablist" aria-label="Layout" style={{ display: "flex", gap: 2, padding: 4, height: 40, flexShrink: 0, boxSizing: "border-box", background: "#F4F1EA", borderRadius: 12 }}>
            {layoutTab("list", "List", <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><rect x="1" y="2" width="14" height="2.4" rx="1" /><rect x="1" y="6.8" width="14" height="2.4" rx="1" /><rect x="1" y="11.6" width="14" height="2.4" rx="1" /></svg>)}
            {layoutTab("panel", "Panel", <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><rect x="1" y="1" width="6" height="6" rx="1.4" /><rect x="9" y="1" width="6" height="6" rx="1.4" /><rect x="1" y="9" width="6" height="6" rx="1.4" /><rect x="9" y="9" width="6" height="6" rx="1.4" /></svg>)}
          </div>
        </div>

        <div style={{ marginTop: 22, display: "flex", alignItems: "center", gap: 12, paddingBottom: 12, borderBottom: "1px solid rgba(42,39,31,0.10)", minHeight: 38 }}>
          {fRenaming ? (
            <input autoFocus data-testid="library-folder-name" value={fDraft} onChange={(e) => setFDraft(e.target.value)} aria-label="Folder name"
              onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") { setFDraft(curFolder?.name ?? ""); setFRenaming(false); } }}
              onBlur={commitFolderRename}
              style={{ height: 36, padding: "0 10px", border: "1.5px solid #597536", borderRadius: 8, background: "#FDFCF9", fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 600, color: "#1A1814", outline: "none" }} />
          ) : (
            <h2 data-testid="library-location-title" style={{ margin: 0, display: "flex", alignItems: "center", gap: 12, fontFamily: "var(--font-serif)", fontSize: 24, fontWeight: 600, letterSpacing: "-0.01em" }}>
              {locDot !== undefined && <CourseDot color={locDot} size={14} />}
              {locTitle}
            </h2>
          )}
          <span style={{ fontSize: 15, color: "#6F6857" }}>{loading ? "" : locCount}</span>
          {lk === "f" && curFolder && (
            <div style={{ display: "flex", gap: 4 }}>
              <button type="button" data-testid="library-rename-folder" className={styles.ghostGreen} onClick={() => { setFDraft(curFolder.name); setFRenaming(true); }}
                style={{ height: 32, padding: "0 10px", border: 0, borderRadius: 8, background: "transparent", color: "#445D22", ...INHERIT_FONT, fontSize: 14, fontWeight: 700, cursor: "pointer" }}>Rename</button>
              <button type="button" data-testid="library-delete-folder" className={styles.ghostRed} onClick={deleteFolder}
                style={{ height: 32, padding: "0 10px", border: 0, borderRadius: 8, background: "transparent", color: "#A8443F", ...INHERIT_FONT, fontSize: 14, fontWeight: 700, cursor: "pointer" }}>Delete Folder</button>
            </div>
          )}
          {!!q && lk !== "all" && (
            <span style={{ marginLeft: "auto", fontSize: 14, color: "#3F3B31" }}>Searching in {scopeName} · <button type="button" data-testid="library-search-all" onClick={() => setLoc("all")}
              style={{ border: 0, padding: 0, background: "transparent", color: "#445D22", ...INHERIT_FONT, fontWeight: 700, cursor: "pointer", textDecoration: "underline", textUnderlineOffset: 3 }}>Search All Documents</button></span>
          )}
        </div>

        {checkedIds.length > 0 && (
          <div data-testid="library-bulk" style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 10, padding: "8px 8px 8px 16px", background: "#1A1814", color: "#FAF8F3", borderRadius: 12, position: "relative", zIndex: 5 }}>
            <span style={{ fontWeight: 700 }}>{checkedIds.length} Selected</span>
            <span style={{ flex: 1 }} />
            <div style={{ position: "relative" }}>
              <button type="button" data-testid="library-bulk-move" onClick={() => setMenu(menu === "bulk" ? null : "bulk")}
                style={{ display: "inline-flex", alignItems: "center", gap: 6, height: 34, padding: "0 12px", border: 0, borderRadius: 8, background: "rgba(250,248,243,0.14)", color: "#FAF8F3", ...INHERIT_FONT, fontSize: 14, fontWeight: 600, cursor: "pointer" }}>
                Move To<Tinted name="chevron-down" size={10} color="currentColor" />
              </button>
              {menu === "bulk" && (
                <div style={{ ...menuPanel, position: "absolute", right: 0, top: 40, width: 240, color: "#1A1814" }}>
                  <span style={menuHeading}>Folder</span>
                  {bulkCourse === undefined && <span style={{ padding: "4px 10px 8px", fontSize: 13, color: "#6F6857" }}>Pick documents from one course to file them together.</span>}
                  {bulkCourse !== undefined && bulkFolders.length === 0 && <span style={{ padding: "4px 10px 8px", fontSize: 13, color: "#6F6857" }}>No folders in this course yet. Use + New to make one.</span>}
                  {bulkFolders.map((f) => (
                    <button key={f.id} data-testid={`library-bulk-folder-${f.id}`} type="button" className={styles.menuItem} onClick={() => move(checkedIds, f.id)} style={{ ...menuItemStyle, padding: "8px 10px", fontWeight: 400 }}>
                      <FolderIcon size={14} />{f.name}
                    </button>
                  ))}
                  {checkedIds.some((id) => placements[id]) && (
                    <button type="button" data-testid="library-bulk-unfile" className={styles.menuItem} onClick={() => move(checkedIds.filter((id) => placements[id]), null)} style={{ ...menuItemStyle, padding: "8px 10px", fontWeight: 400 }}>
                      Remove From Folder
                    </button>
                  )}
                </div>
              )}
            </div>
            <button type="button" data-testid="library-bulk-delete" onClick={() => (bulkConfirm ? remove(checkedIds) : setBulkConfirm(true))}
              style={{ height: 34, padding: "0 12px", border: 0, borderRadius: 8, background: bulkConfirm ? "#A8443F" : "rgba(250,248,243,0.14)", color: "#FAF8F3", ...INHERIT_FONT, fontSize: 14, fontWeight: 600, cursor: "pointer" }}>
              {bulkConfirm ? "Click Again to Delete" : "Delete"}
            </button>
            <button type="button" data-testid="library-bulk-clear" onClick={() => { setChecked({}); setMenu(null); setBulkConfirm(false); }}
              style={{ height: 34, padding: "0 12px", border: 0, borderRadius: 8, background: "transparent", color: "#FAF8F3", ...INHERIT_FONT, fontSize: 14, cursor: "pointer", textDecoration: "underline", textUnderlineOffset: 3 }}>Clear</button>
          </div>
        )}

        <div className={styles.scroll} onScroll={markScrolling} style={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden", padding: "4px 6px 96px 0" }}>
          {loading ? (
            <div style={{ paddingTop: 16 }}>{view === "panel" ? <LibraryGridSkeleton /> : <LibraryListSkeleton />}</div>
          ) : loadError && documents.length === 0 ? (
            <div data-testid="library-load-error" role="alert" style={{ maxWidth: 440, margin: "72px auto 0", textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
              <div style={{ fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 600 }}>Couldn&apos;t Load Your Library</div>
              <div style={{ fontSize: 15, color: "#3F3B31" }}>Your documents are safe. Check your connection and try again.</div>
              <button type="button" data-testid="library-load-retry" onClick={retryLoad}
                style={{ marginTop: 6, height: 38, padding: "0 16px", border: 0, background: "#445D22", color: "#FFFFFF", borderRadius: 10, ...INHERIT_FONT, fontSize: 14, fontWeight: 700, cursor: "pointer" }}>Try Again</button>
            </div>
          ) : (
            <>
              {loadError && (
                <div data-testid="library-load-error" role="alert" style={{ marginTop: 10, fontSize: 14, color: "#6F6857", display: "flex", alignItems: "center", gap: 8 }}>
                  Couldn&apos;t refresh your library. Showing what was last loaded.
                  <button type="button" data-testid="library-load-retry" onClick={retryLoad} style={{ border: 0, background: "transparent", color: "#445D22", fontWeight: 700, cursor: "pointer", ...INHERIT_FONT }}>Retry</button>
                </div>
              )}

              {!empty && view === "list" && (
                <>
                  <div role="row" style={{ display: "grid", gridTemplateColumns: listCols, gap: 12, minWidth: 0, alignItems: "center", padding: "12px 14px 8px", fontSize: 13, fontWeight: 600, color: "#6F6857" }}>
                    <CheckBox checked={allChecked} label="Select all" onClick={() => setChecked(allChecked ? {} : Object.fromEntries(list.map((d) => [d.id, true])))} />
                    <span>Name</span>{lk === "all" && <span>Course</span>}<span>Type</span><span style={{ textAlign: "right" }}>Added</span>
                  </div>
                  {folderItems.map((f) => {
                    const key = `f:${f.id}`, dr = dropOn === key, editing = edit?.id === f.id;
                    const n = liveDocs.filter((d) => folderOf(d) === f.id).length;
                    return (
                      <div key={f.id} role="row" tabIndex={0} data-testid={`library-folder-item-${f.id}`} className={styles.folderRow}
                        onClick={() => !editing && pickLoc(key as Loc)} {...dropProps(key, (ids) => move(ids, f.id))}
                        style={{ display: "grid", gridTemplateColumns: listCols, gap: 12, minWidth: 0, alignItems: "center", padding: "10px 14px", borderRadius: 12, background: dr ? "#DCE8CE" : "transparent", boxShadow: dr ? "inset 0 0 0 1.5px #597536" : "none", cursor: "pointer" }}>
                        <span />
                        <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
                          <span style={{ width: 30, height: 38, display: "grid", placeItems: "center", flexShrink: 0 }}><FolderIcon size={30} strokeWidth={1.6} /></span>
                          <div style={{ minWidth: 0, flex: 1 }}>
                            {editing ? editInput() : <div style={{ fontSize: 16, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{f.name}</div>}
                            <div style={{ fontSize: 14, color: "#6F6857" }}>{n} {n === 1 ? "document" : "documents"}</div>
                          </div>
                        </div>
                        {lk === "all" && <span />}
                        <span style={{ fontSize: 14, color: "#3F3B31" }}>Folder</span>
                        <span style={{ display: "flex", justifyContent: "flex-end", color: "#6F6857" }}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 5l7 7-7 7" /></svg>
                        </span>
                      </div>
                    );
                  })}
                  {pendingDoc && (
                    <div role="row" style={{ display: "grid", gridTemplateColumns: listCols, gap: 12, minWidth: 0, alignItems: "center", padding: "10px 14px", borderRadius: 12, background: "#EBF0E1", boxShadow: "inset 0 0 0 1px rgba(68,93,34,0.25)" }}>
                      <span />
                      <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
                        {fmtTile("NOTE", "New note")}
                        <div style={{ minWidth: 0, flex: 1 }}>
                          {editInput()}
                          <div style={{ fontSize: 14, color: "#6F6857" }}>Opens in the Notetaker</div>
                        </div>
                      </div>
                      {lk === "all" && <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}><CourseDot color={pendingCourse?.color ?? null} />{pendingCourse?.code ?? ""}</span>}
                      <span style={{ fontSize: 14, color: "#3F3B31" }}>Note</span>
                      <span style={{ fontSize: 14, color: "#6F6857", textAlign: "right" }}>Today</span>
                    </div>
                  )}
                  {list.map((d) => {
                    const r = rowProps(d), c = courseOf(d), fmt = fileFormat(d.file_name), sub = subLine(d), t = typeOf(d.category);
                    return (
                      <div key={d.id} role="row" tabIndex={0} aria-selected={r.on} data-on={r.on} data-testid={`library-doc-${d.id}`} draggable
                        className={styles.row} onDragStart={r.dragStart} onDragEnd={r.dragEnd} onClick={r.pick} onDoubleClick={r.rename}
                        onKeyDown={(e) => { if (e.key === "Enter" && e.target === e.currentTarget) r.pick(); }}
                        style={{ display: "grid", gridTemplateColumns: listCols, gap: 12, minWidth: 0, alignItems: "center", padding: "10px 14px", borderRadius: 12, background: r.on ? "#EBF0E1" : "transparent", boxShadow: r.on ? "inset 0 0 0 1px rgba(68,93,34,0.25)" : "none", cursor: "pointer", opacity: r.op }}>
                        <CheckBox checked={r.ck} label={r.ck ? `Deselect ${displayTitle(d.file_name)}` : `Select ${displayTitle(d.file_name)}`} onClick={r.check} />
                        <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
                          {fmtTile(fmt, `${t.label} · ${fmt}`)}
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: 16, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{titleOf(d)}</div>
                            <div style={{ fontSize: 14, color: sub.hit ? "#445D22" : "#6F6857", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{sub.text}</div>
                          </div>
                        </div>
                        {lk === "all" && (
                          <span style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0, fontSize: 14 }}>
                            <CourseDot color={c?.color ?? null} />
                            <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: c ? "#1A1814" : "#6F6857" }}>{c ? c.code : "Uncategorized"}</span>
                          </span>
                        )}
                        <span style={{ fontSize: 14, color: "#3F3B31" }}>{t.label}</span>
                        <span style={{ fontSize: 14, color: "#6F6857", textAlign: "right" }}>{addedLabel(d.created_at)}</span>
                      </div>
                    );
                  })}
                </>
              )}

              {!empty && view === "panel" && (
                <div style={{ paddingTop: 16, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))", gap: 18 }}>
                  {folderItems.map((f) => {
                    const key = `f:${f.id}`, dr = dropOn === key, editing = edit?.id === f.id;
                    const n = liveDocs.filter((d) => folderOf(d) === f.id).length;
                    return (
                      <div key={f.id} role="button" tabIndex={0} onClick={() => !editing && pickLoc(key as Loc)} {...dropProps(key, (ids) => move(ids, f.id))}
                        style={{ display: "flex", flexDirection: "column", borderRadius: 14, background: "#FDFCF9", border: `1px solid ${dr ? "#597536" : "rgba(42,39,31,0.12)"}`, boxShadow: "0 1px 2px rgba(25,37,11,0.04)", overflow: "hidden", cursor: "pointer" }}>
                        <div style={{ height: 176, background: dr ? "#DCE8CE" : "#EFEBE2", display: "grid", placeItems: "center" }}><FolderIcon size={84} strokeWidth={1.6} /></div>
                        <div style={{ padding: "12px 14px 14px", display: "flex", flexDirection: "column", gap: 4, borderTop: "1px solid rgba(42,39,31,0.10)" }}>
                          {editing ? editInput(15) : <div style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.3 }}>{f.name}</div>}
                          <div style={{ fontSize: 13, color: "#6F6857" }}>Folder · {n} {n === 1 ? "document" : "documents"}</div>
                        </div>
                      </div>
                    );
                  })}
                  {pendingDoc && (
                    <div style={{ display: "flex", flexDirection: "column", borderRadius: 14, background: "#FDFCF9", border: "1px solid #597536", overflow: "hidden" }}>
                      <PageCard compact h="Untitled" lines={["Start writing here."]} accent={TYPES.other.color} />
                      <div style={{ padding: "12px 14px 14px", display: "flex", flexDirection: "column", gap: 4, borderTop: "1px solid rgba(42,39,31,0.10)", background: "#F2F6EE" }}>
                        {editInput(15)}
                        <div style={{ fontSize: 13, color: "#6F6857" }}>Note · opens in the Notetaker</div>
                      </div>
                    </div>
                  )}
                  {list.map((d) => {
                    const r = rowProps(d), c = courseOf(d), t = typeOf(d.category), page = pageOf(d);
                    return (
                      <div key={d.id} role="button" tabIndex={0} aria-pressed={r.on} data-testid={`library-doc-${d.id}`} draggable
                        onDragStart={r.dragStart} onDragEnd={r.dragEnd} onClick={r.pick} onDoubleClick={r.rename}
                        onKeyDown={(e) => { if (e.key === "Enter" && e.target === e.currentTarget) r.pick(); }}
                        style={{ position: "relative", display: "flex", flexDirection: "column", borderRadius: 14, background: "#FDFCF9", border: `1px solid ${r.on ? "#597536" : "rgba(42,39,31,0.12)"}`, boxShadow: r.on ? "0 0 0 2px rgba(89,117,54,0.25), 0 6px 18px rgba(25,37,11,0.08)" : "0 1px 2px rgba(25,37,11,0.04)", overflow: "hidden", cursor: "pointer", opacity: r.op }}>
                        <PageCard compact h={page.h} lines={page.lines} accent={t.color} />
                        <div style={{ position: "absolute", top: 10, left: 10 }}>
                          <CheckBox card size={22} checked={r.ck} label={r.ck ? `Deselect ${displayTitle(d.file_name)}` : `Select ${displayTitle(d.file_name)}`} onClick={r.check} />
                        </div>
                        <div style={{ padding: "12px 14px 14px", display: "flex", flexDirection: "column", gap: 4, borderTop: "1px solid rgba(42,39,31,0.10)", background: r.on ? "#F2F6EE" : "#FDFCF9" }}>
                          <div style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.3, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{titleOf(d)}</div>
                          <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 13, color: "#6F6857" }}>
                            {lk === "all" && <CourseDot color={c?.color ?? null} />}
                            {(lk === "all" ? `${c ? c.code : "Uncategorized"} · ` : "") + `${t.label} · ${fileFormat(d.file_name)}`}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {empty && (
                <div style={{ maxWidth: 440, margin: "72px auto 0", textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
                  <div style={{ fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 600 }}>
                    {q ? `No Documents Match “${query.trim()}”` : type !== "all" ? `No ${TYPES[type].label} Here` : lk === "f" ? "This Folder Is Empty" : "Nothing Here Yet"}
                  </div>
                  <div style={{ fontSize: 15, color: "#3F3B31", textWrap: "pretty" }}>
                    {q ? (lk !== "all" ? `Nothing in ${scopeName} matches. Try searching all documents, or search for a concept name.` : "Try a shorter word, a course code, or a concept name.")
                      : lk === "f" ? "Drag documents here, or use Add to Folder in a document's menu."
                      : "Upload a syllabus, lecture notes, or a reading and Sapling will summarize it."}
                  </div>
                  <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
                    {query && <button type="button" data-testid="library-empty-clear" onClick={() => setQuery("")} style={{ height: 38, padding: "0 16px", border: "1.5px solid #445D22", background: "transparent", color: "#445D22", borderRadius: 10, ...INHERIT_FONT, fontSize: 14, fontWeight: 700, cursor: "pointer" }}>Clear Search</button>}
                    {!!q && lk !== "all" && <button type="button" data-testid="library-empty-search-all" onClick={() => setLoc("all")} style={{ height: 38, padding: "0 16px", border: 0, background: "#445D22", color: "#FFFFFF", borderRadius: 10, ...INHERIT_FONT, fontSize: 14, fontWeight: 700, cursor: "pointer" }}>Search All Documents</button>}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {toastState && (
          <div role="status" data-testid="library-toast" style={{ position: "absolute", left: "50%", bottom: 28, transform: "translateX(-50%)", display: "flex", alignItems: "center", gap: 16, padding: "10px 10px 10px 18px", background: "#1A1814", color: "#FAF8F3", borderRadius: 12, boxShadow: "0 12px 30px rgba(25,37,11,0.24)", fontSize: 15, whiteSpace: "nowrap", zIndex: 20 }}>
            <span>{toastState.msg}</span>
            {toastState.undo && (
              <button type="button" data-testid="library-undo" onClick={undo} style={{ height: 32, padding: "0 12px", border: 0, borderRadius: 8, background: "rgba(250,248,243,0.14)", color: "#D9E7C4", ...INHERIT_FONT, fontSize: 14, fontWeight: 700, cursor: "pointer" }}>Undo</button>
            )}
          </div>
        )}
      </section>

      {!isMobile && (
        <LibraryPreview
          doc={pv}
          course={pv ? courseOf(pv) : null}
          folderName={pv && folderOf(pv) ? folderById.get(folderOf(pv)!)!.name : null}
          folderOptions={pv ? liveFolders.filter((f) => f.course_id === (pv.course_id ?? null) && !f.id.startsWith(TMP)).map((f) => ({ id: f.id, name: f.name, on: folderOf(pv) === f.id })) : []}
          renaming={renaming && !!pv}
          onStartRename={() => setRenaming(true)}
          onEndRename={endDocRename}
          onToggleFolder={(fid) => pv && move([pv.id], folderOf(pv) === fid ? null : fid)}
          onDelete={() => pv && remove([pv.id])}
          onOpen={() => pv && setReading(pv)}
        />
      )}

      {reading && (
        <LibraryReader
          doc={reading}
          courseLabel={courseOf(reading)?.code ?? "Uncategorized"}
          onClose={() => setReading(null)}
        />
      )}

      <DocumentUploadModal
        open={uploadOpen}
        userId={userId}
        courses={courses}
        onClose={() => setUploadOpen(false)}
        onComplete={async (items) => {
          const hasSyllabus = items.some((it) => it.category === "syllabus");
          await load();
          if (hasSyllabus) {
            // Brief delay for server-side ingestion races, then reload again.
            setTimeout(load, 1500);
            toast.info("Syllabus processed. New assignments will appear on the calendar.");
          }
        }}
      />
    </div>
  );
}
