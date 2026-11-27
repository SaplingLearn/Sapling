"use client";
/**
 * The Notes page, rebuilt from `designs/Sapling Notes.dc.html`.
 *
 * A document's generated notes, editable in place: a floating toolbar over a
 * 944px column, every insertable block, equations edited without a LaTeX box,
 * and Ask Clov beside it.
 *
 * The editor is an UNCONTROLLED `contentEditable` — React writes its HTML once
 * when the notes load and never again, because re-rendering it would move the
 * caret on every keystroke. Everything that reads it goes through the ref.
 */
import React from "react";
import { useRouter } from "next/navigation";

import { FullHeightScreen } from "../FullHeightScreen";
import { useConfirm } from "@/lib/useConfirm";
import { useUser } from "@/context/UserContext";
import { getCourses, getDocuments, type EnrolledCourse } from "@/lib/api";
import type { Document as Doc } from "@/lib/types";
import { courseLabel, dedupeCourses, titleOf } from "../library/libraryModel";

import { exportHTML, exportMarkdown, download, fileBase, printPDF } from "@/lib/notes/export";
import { editedLabel, useDocumentNotes } from "@/lib/notes/useDocumentNotes";
import { useClovChat, type ClovMessage } from "@/lib/notes/useClovChat";
import { useNoteBlocks } from "@/lib/notes/useNoteBlocks";
import { useNoteEditor } from "@/lib/notes/useNoteEditor";
import { useNoteGraphs } from "@/lib/notes/useNoteGraphs";
import { useNoteMath } from "@/lib/notes/useNoteMath";

import { ClovButton, ClovPanel, CLOV_WIDTH } from "./ClovPanel";
import { MathPalette } from "./MathPalette";
import { NotesHeader, type HeaderMenu } from "./NotesHeader";
import { NotesSkeleton } from "./NotesSkeleton";
import { NotesToast, useNotesToast } from "./NotesToast";
import { SelectionBubble } from "./SelectionBubble";
import { NotesToolbar, type ToolbarMenu } from "./NotesToolbar";
import { ROW_WIDTHS, SQUEEZE } from "./toolbarModel";
import { useNotesSelection } from "./useNotesSelection";

/** The skeleton's beat, matched to the Library's. */
const BOOT_MS = 980;
/** Where the collapsed state of Ask Clov is remembered. */
const CLOV_KEY = "sapling:clovClosed";
/** The design's menu-exit duration. */
const MENU_EXIT_MS = 130;

export function Notes({ documentId }: { documentId: string }) {
  const router = useRouter();
  const toast = useNotesToast();
  const { userId, userReady } = useUser();

  const editorRef = React.useRef<HTMLDivElement>(null);
  const titleRef = React.useRef<HTMLDivElement>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const sectionRef = React.useRef<HTMLElement>(null);
  const leftRef = React.useRef<HTMLDivElement>(null);
  const barRef = React.useRef<HTMLDivElement>(null);
  const rightRef = React.useRef<HTMLDivElement>(null);

  const [booted, setBooted] = React.useState(false);
  React.useEffect(() => {
    const t = setTimeout(() => setBooted(true), BOOT_MS);
    return () => clearTimeout(t);
  }, []);

  const [clovOpen, setClovOpen] = React.useState(true);
  React.useEffect(() => {
    try { setClovOpen(localStorage.getItem(CLOV_KEY) !== "1"); } catch { /* private mode */ }
  }, []);
  const toggleClov = React.useCallback(() => {
    setClovOpen(open => {
      try { localStorage.setItem(CLOV_KEY, open ? "1" : "0"); } catch { /* private mode */ }
      return !open;
    });
  }, []);

  const [toolbarMenu, setToolbarMenu] = React.useState<ToolbarMenu>(null);
  const [headerMenu, setHeaderMenu] = React.useState<HeaderMenu>(null);
  const [menuClosing, setMenuClosing] = React.useState(false);
  const exitTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const closeMenus = React.useCallback(() => {
    setMenuClosing(true);
    if (exitTimer.current) clearTimeout(exitTimer.current);
    exitTimer.current = setTimeout(() => {
      setMenuClosing(false);
      setToolbarMenu(null);
      setHeaderMenu(null);
    }, MENU_EXIT_MS);
  }, []);
  React.useEffect(() => () => {
    if (exitTimer.current) clearTimeout(exitTimer.current);
  }, []);

  const openToolbarMenu = React.useCallback((m: ToolbarMenu) => {
    if (m === null) { closeMenus(); return; }
    if (exitTimer.current) clearTimeout(exitTimer.current);
    setMenuClosing(false);
    setHeaderMenu(null);
    setToolbarMenu(m);
  }, [closeMenus]);

  const openHeaderMenu = React.useCallback((m: HeaderMenu) => {
    if (m === null) { closeMenus(); return; }
    if (exitTimer.current) clearTimeout(exitTimer.current);
    setMenuClosing(false);
    setToolbarMenu(null);
    setHeaderMenu(m);
  }, [closeMenus]);

  // ── the document this page is about ─────────────────────────────────────
  const [doc, setDoc] = React.useState<Doc | null>(null);
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  React.useEffect(() => {
    if (!userReady || !userId) return;
    let live = true;
    void Promise.all([getDocuments(userId), getCourses(userId)])
      .then(([d, c]) => {
        if (!live) return;
        setDoc(d.documents.find((x: Doc) => x.id === documentId) ?? null);
        setCourses(dedupeCourses(c.courses || []));
      })
      .catch(err => console.error("notes document load failed", err));
    return () => { live = false; };
  }, [documentId, userId, userReady]);

  const course = doc?.course_id
    ? courses.find(c => c.course_id === doc.course_id)
    : undefined;

  // ── notes: load, autosave, regenerate ───────────────────────────────────
  const readNotes = React.useCallback(() => editorRef.current?.innerHTML ?? "", []);
  const writeNotes = React.useCallback((html: string) => {
    const ed = editorRef.current;
    if (ed) ed.innerHTML = html;
  }, []);

  const notes = useDocumentNotes({
    documentId, userId, ready: userReady && !!userId, read: readNotes, write: writeNotes,
  });

  // The page opened but the opening draft could not be written (the model was
  // unavailable). Said once, because an empty editor otherwise reads as notes
  // that went missing rather than a draft that never arrived.
  const draftFailed = notes.draftFailed;
  const toldDraftFailed = React.useRef(false);
  React.useEffect(() => {
    if (!draftFailed || toldDraftFailed.current) return;
    toldDraftFailed.current = true;
    toast.flash(
      "Couldn't write the opening notes just now — this page is yours to "
      + "write in, or press Regenerate to try again.",
    );
  }, [draftFailed, toast]);

  // The title is contentEditable too, so it is written rather than bound.
  React.useEffect(() => {
    const el = titleRef.current;
    if (el && document.activeElement !== el && el.textContent !== notes.title) {
      el.textContent = notes.title;
    }
  }, [notes.title]);

  // ── the editor's parts ──────────────────────────────────────────────────
  const graphs = useNoteGraphs({ rootRef: editorRef, onChange: notes.touch });
  const math = useNoteMath({
    rootRef: editorRef, onChange: notes.touch, readOnly: notes.final,
  });

  const afterInsert = React.useCallback(() => {
    math.refresh();
    graphs.refresh();
  }, [math, graphs]);

  const editor = useNoteEditor({
    editorRef, onChange: notes.touch, afterInsert, readOnly: notes.final,
  });
  const blocks = useNoteBlocks({ onChange: notes.touch, refresh: afterInsert });

  // Render the loaded markup once it is in the DOM.
  React.useEffect(() => {
    if (!notes.loading && !notes.error) afterInsert();
  }, [notes.loading, notes.error, afterInsert]);

  // ── Ask Clov ────────────────────────────────────────────────────────────
  const [copied, setCopied] = React.useState<number | null>(null);
  const clov = useClovChat({
    documentId,
    userId,
    readNotes: () => editorRef.current?.innerText ?? "",
    openPanel: () => setClovOpen(true),
  });

  /** Where a "Replace Selection" reply should go. */
  const rewriteRange = React.useRef<Range | null>(null);

  const insertReply = React.useCallback((m: ClovMessage) => {
    const ed = editorRef.current;
    if (!ed) return;

    if (m.forRewrite && rewriteRange.current) {
      ed.focus();
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(rewriteRange.current);
      document.execCommand("insertText", false, m.text);
      rewriteRange.current = null;
      notes.touch();
      toast.flash("Replaced the selected text");
      return;
    }

    // A reply goes in as a quote, below whatever block the caret was in, so
    // it is visibly Clov's words until the student edits them.
    const quote = document.createElement("blockquote");
    quote.textContent = m.text;
    let anchor = editor.lastRange.current && ed.contains(editor.lastRange.current.startContainer)
      ? (editor.lastRange.current.startContainer as Node | null)
      : null;
    while (anchor && anchor.parentNode !== ed) anchor = anchor.parentNode;
    if (anchor) (anchor as HTMLElement).after(quote);
    else ed.appendChild(quote);

    const sc = scrollRef.current;
    if (sc) sc.scrollTop = Math.max(0, quote.offsetTop - 160);
    notes.touch();
    toast.flash(anchor ? "Added below your cursor" : "Added to the end of your notes");
  }, [editor.lastRange, notes, toast]);

  // ── the selection bubble ────────────────────────────────────────────────
  const selection = useNotesSelection({
    editorRef,
    sectionRef,
    enabled: !notes.final,
    onAsk: text => { clov.setQuote(text); setClovOpen(true); },
    onExplain: text => clov.ask("Explain this in simpler terms.", text),
    onImprove: (text, range) => {
      rewriteRange.current = range;
      clov.ask("Improve the wording of this passage. Rewrite it.", text, true);
    },
    onHighlight: range => {
      const ed = editorRef.current;
      if (!ed) return;
      ed.focus();
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
      document.execCommand("hiliteColor", false, "#F6E7B0");
      sel?.collapseToEnd();
      notes.touch();
    },
  });

  // ── how much of the header row is left for the toolbar? ─────────────────
  // A pure function of the layout: the header's width and the breadcrumb's,
  // neither of which changes with what is decided here. The bar's and the
  // actions' two sizes are constants (`ROW_WIDTHS`) rather than live reads,
  // because a live read of either is a reading of the current answer — and
  // deciding from it made the row flip between states and settle wherever
  // the last pass left it.
  //
  // Order matters: the labels come down first, and only a row that still
  // cannot seat the narrow bar gives it a row of its own. A bar you have to
  // scroll sideways is worse than a bar on the next line, which is what the
  // squeezed toolbar beside an open Clov panel was.
  const [compact, setCompact] = React.useState(false);
  const [mini, setMini] = React.useState(false);
  const [stacked, setStacked] = React.useState(false);
  React.useEffect(() => {
    // Found from the BREADCRUMB, which never leaves the header — not from
    // the bar, which does. Resolving it through the bar meant that the moment
    // the bar took its own row the lookup returned null, the effect bailed,
    // and the row could never be re-measured: stacking latched on for good.
    // Re-resolved inside `measure` for the same reason.
    const measure = () => {
      const bar = barRef.current;
      const left = leftRef.current;
      const header = left?.closest("header") as HTMLElement | null;
      if (!bar || !left || !header) return;
      // Nothing to measure — a server render, jsdom, a hidden container —
      // so show the row the handoff draws rather than read zero as "no room".
      if (!header.clientWidth) { setCompact(false); setStacked(false); return; }

      const cs = getComputedStyle(header);
      const pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
      const gaps = parseFloat(cs.gap || "0") * 3;
      const back = (header.firstElementChild as HTMLElement | null)?.offsetWidth ?? 0;
      const room = header.clientWidth - pad - gaps - back - left.offsetWidth;

      // Four sizes, each tried before the one below it, and the row only
      // breaks when none of them fit:
      //   wide    the handoff's bar, actions written out
      //   narrow  action labels down, the bar's labels with them
      //   mini    the bar taken in again, style control down to its chevron
      //   own row the bar cannot be seated at all
      // With Clov open the bar already wears the narrow metrics for the
      // panel's sake, so `compact` has nothing of its own to take off.
      const forWide = room - ROW_WIDTHS.wideActions;
      const forNarrow = room - ROW_WIDTHS.narrowActions;
      const tight = clovOpen || forWide < ROW_WIDTHS.wideBar + 40;
      const tooTightForNarrow = tight && forNarrow < ROW_WIDTHS.narrowBar + 16;

      setCompact(!clovOpen && tight);
      // A thin margin here on purpose: mini is the last size that keeps the
      // row together, so it is worth using whenever it genuinely fits. The
      // wider margin above belongs to `wide`, where overshooting only costs
      // the action labels rather than the line.
      setMini(tooTightForNarrow && forNarrow >= ROW_WIDTHS.miniBar + 4);
      setStacked(tooTightForNarrow && forNarrow < ROW_WIDTHS.miniBar + 4);
    };
    measure();
    window.addEventListener("resize", measure);
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    const head = leftRef.current?.closest("header");
    if (ro && head) ro.observe(head);
    if (ro && leftRef.current) ro.observe(leftRef.current);
    // Clov slides for 380ms and the fonts land a little after; these passes
    // read the row once it has stopped moving.
    const timers = [450, 1200].map(ms => setTimeout(measure, ms));
    return () => {
      window.removeEventListener("resize", measure);
      ro?.disconnect();
      timers.forEach(clearTimeout);
    };
  }, [clovOpen, notes.title, notes.final, notes.saveState]);

  // ── header actions ──────────────────────────────────────────────────────
  const docTitle = notes.title || (doc ? titleOf(doc) : "Notes");
  const courseName = course ? courseLabel(course) : "No Course";
  const metaLine = `${courseName} · ${editedLabel(notes.editedAt, "today")}`;

  const share = React.useCallback(() => {
    const url = window.location.href;
    void (async () => {
      if (navigator.share) {
        try { await navigator.share({ title: docTitle, url }); return; } catch { return; }
      }
      try {
        await navigator.clipboard.writeText(url);
        toast.flash("Link copied");
      } catch {
        toast.flash("Couldn't copy the link");
      }
    })();
  }, [docTitle, toast]);

  const downloads = React.useMemo(() => {
    const html = () => {
      const ed = editorRef.current;
      return ed ? exportHTML(ed, docTitle, metaLine) : "";
    };
    const base = fileBase(docTitle);
    return [
      { label: "Web page", ext: ".html", run: () => download(`${base}.html`, html(), "text/html") },
      {
        label: "Markdown",
        ext: ".md",
        run: () => {
          const ed = editorRef.current;
          if (ed) download(`${base}.md`, exportMarkdown(ed, docTitle), "text/markdown");
        },
      },
      { label: "PDF", ext: ".pdf", run: () => printPDF(html(), base) },
    ];
  }, [docTitle, metaLine]);

  const toggleFinal = React.useCallback(() => {
    const next = !notes.final;
    const ed = editorRef.current;
    if (next && ed) {
      // Finalizing settles every block into its read-only shape, so what is
      // saved is what a reader will see.
      ed.querySelectorAll(".blk.gx").forEach(b => b.setAttribute("data-final", "1"));
      ed.querySelectorAll('.blk[data-blk="table"]').forEach(b => b.setAttribute("data-edit", "0"));
      math.close();
    }
    notes.setFinal(next);
    closeMenus();
    toast.flash(next ? "Finalized. Now read-only." : "Editing turned back on");
  }, [notes, math, closeMenus, toast]);

  // Regenerate throws the student's edits away, so it asks first — the
  // repo's two-step confirm, which the design's own copy calls for.
  const regenerate = useConfirm(async () => {
    const ok = await notes.regenerate();
    if (ok) {
      afterInsert();
      toast.flash(`Notes regenerated from ${doc ? titleOf(doc) : "the document"}`);
    } else {
      toast.flash("Couldn't regenerate these notes.");
    }
  });

  const back = React.useCallback(() => {
    void notes.flush().finally(() => router.push("/library"));
  }, [notes, router]);

  const editable = !notes.final && !notes.loading && !notes.error;

  return (
    <FullHeightScreen>
      <main
        // Scopes the design's scrollbar and reduced-motion rule to this page.
        data-sap-surface=""
        style={{
          position: "relative", flex: 1, minWidth: 0, display: "flex", flexDirection: "column",
          background: "#FAF8F3", color: "#1A1814", fontSize: 15, lineHeight: 1.45,
          WebkitFontSmoothing: "antialiased",
        }}
      >
        {editable && stacked && (
          // Under the header, spanning the editor column. The header is 76px
          // tall and the document's own content starts at 112px, so this sits
          // in the gap rather than over either.
          <div style={{
            position: "absolute", top: 72, left: 28,
            right: (clovOpen ? CLOV_WIDTH : 0) + 28,
            zIndex: 11, display: "flex", justifyContent: "center",
            transition: `right ${SQUEEZE}`,
          }}>
            <NotesToolbar
              stacked={stacked}
            formats={editor.formats}
            clovOpen={clovOpen}
            compact={compact}
            mini={mini}
            barRef={barRef}
            menu={toolbarMenu}
            onMenu={openToolbarMenu}
            menuClosing={menuClosing}
            exec={editor.exec}
            insertHTML={editor.insertHTML}
            insertCode={editor.insertCode}
            insertLink={editor.insertLink}
            insertEquation={() => {
              editor.restore();
              document.execCommand(
                "insertHTML", false,
                '<span class="imath" contenteditable="false" data-tex="" data-new="1"></span>&#8203;',
              );
              const el = editorRef.current?.querySelector<HTMLElement>('.imath[data-new="1"]');
              if (el) {
                el.removeAttribute("data-new");
                math.open(el);
              }
              notes.touch();
            }}
            insertBlock={editor.insertHTML}
            insertGraph={kind => editor.insertHTML(graphs.html(kind))}
            setBlockStyle={block => editor.exec("formatBlock", block)}
            />
          </div>
        )}

        {!booted && <NotesSkeleton clovOpen={clovOpen} />}

        <NotesHeader
          courseLabel={courseName}
          courseColor={course?.color || "#8A8372"}
          docTitle={docTitle}
          saveState={notes.saveState}
          clovOpen={clovOpen}
          compact={compact}
          final={notes.final}
          onBack={back}
          onShare={share}
          onToggleFinal={toggleFinal}
          onRegenerate={regenerate.trigger}
          regenerating={notes.regenerating}
          menu={headerMenu}
          onMenu={openHeaderMenu}
          menuClosing={menuClosing}
          downloads={downloads}
          center={editable && !stacked ? (
            <NotesToolbar
              stacked={stacked}
            formats={editor.formats}
            clovOpen={clovOpen}
            compact={compact}
              mini={mini}
            barRef={barRef}
            menu={toolbarMenu}
            onMenu={openToolbarMenu}
            menuClosing={menuClosing}
            exec={editor.exec}
            insertHTML={editor.insertHTML}
            insertCode={editor.insertCode}
            insertLink={editor.insertLink}
            insertEquation={() => {
              editor.restore();
              document.execCommand(
                "insertHTML", false,
                '<span class="imath" contenteditable="false" data-tex="" data-new="1"></span>&#8203;',
              );
              const el = editorRef.current?.querySelector<HTMLElement>('.imath[data-new="1"]');
              if (el) {
                el.removeAttribute("data-new");
                math.open(el);
              }
              notes.touch();
            }}
            insertBlock={editor.insertHTML}
            insertGraph={kind => editor.insertHTML(graphs.html(kind))}
            setBlockStyle={block => editor.exec("formatBlock", block)}
            />
          ) : undefined}
          leftRef={leftRef}
          rightRef={rightRef}
        />

        {regenerate.armed && (
          <div role="alert" data-testid="notes-regenerate-confirm" style={{
            position: "absolute", top: 72, right: clovOpen ? CLOV_WIDTH + 28 : 28, zIndex: 13,
            width: 300, padding: "12px 14px", background: "#FDFCF9",
            border: "1px solid rgba(42,39,31,0.14)", borderRadius: 12,
            boxShadow: "0 14px 36px rgba(25,37,11,0.16)", fontSize: 14, color: "#3F3B31",
            transition: `right ${SQUEEZE}`,
          }}>
            Regenerating replaces everything you have written here.
            Click Regenerate again to confirm.
          </div>
        )}

        

        <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
          <section
            ref={sectionRef}
            aria-label="Notes"
            style={{
              position: "relative", flex: 1, minWidth: 0, display: "flex",
              flexDirection: "column",
            }}
          >
            <div
              ref={scrollRef}
              data-edscroll=""
              onScroll={selection.hide}
              style={{ flex: 1, minHeight: 0, overflowY: "auto" }}
            >
              <div style={{
                animation: "sapSlideUp 420ms cubic-bezier(0.2, 0.7, 0.2, 1) 880ms both",
                maxWidth: 1040, margin: "0 auto", padding: "112px 48px 96px",
                transition: `padding-top ${SQUEEZE}`,
              }}>
                {notes.error ? (
                  <div role="alert" data-testid="notes-load-error" style={{
                    maxWidth: 440, margin: "72px auto 0", textAlign: "center",
                    display: "flex", flexDirection: "column", alignItems: "center", gap: 10,
                  }}>
                    <div style={{
                      fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 600,
                    }}>Couldn&apos;t open these notes</div>
                    <div style={{ fontSize: 15, color: "#3F3B31" }}>
                      Your document is safe. Check your connection and try again.
                    </div>
                    <button
                      data-testid="notes-load-retry"
                      className="sapHoverForest"
                      onClick={notes.retry}
                      style={{
                        marginTop: 6, height: 38, padding: "0 16px", border: 0,
                        background: "#445D22", color: "#FFFFFF", borderRadius: 10,
                        font: "inherit", fontSize: 14, fontWeight: 700, cursor: "pointer",
                      }}
                    >Try again</button>
                  </div>
                ) : (
                  <>
                    <div style={{
                      display: "flex", alignItems: "flex-start", gap: 20, marginBottom: 22,
                    }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div
                          ref={titleRef}
                          data-title=""
                          data-testid="notes-title"
                          data-placeholder="Untitled"
                          contentEditable={!notes.final}
                          suppressContentEditableWarning
                          spellCheck={false}
                          onInput={e => notes.setTitle(e.currentTarget.textContent || "")}
                          onKeyDown={e => {
                            if (e.key !== "Enter") return;
                            // Enter in the title moves into the body rather
                            // than putting a line break in a heading.
                            e.preventDefault();
                            const ed = editorRef.current;
                            if (!ed) return;
                            ed.focus();
                            const range = document.createRange();
                            range.setStart(ed, 0);
                            range.collapse(true);
                            const sel = window.getSelection();
                            sel?.removeAllRanges();
                            sel?.addRange(range);
                          }}
                          role="textbox"
                          aria-label="Document title"
                          style={{
                            fontFamily: "var(--font-serif)", fontSize: 40, lineHeight: 1.12,
                            fontWeight: 600, letterSpacing: "-0.02em", color: "#1A1814",
                            textWrap: "balance", outline: "none", caretColor: "#445D22",
                          }}
                        />
                        <div style={{
                          display: "flex", alignItems: "center", gap: 10, marginTop: 10,
                          fontSize: 14, color: "#6F6857",
                        }}>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
                            <span style={{
                              width: 9, height: 9, borderRadius: "50%",
                              background: course?.color || "#8A8372",
                            }} />
                            {courseName}
                          </span>
                          <span>·</span>
                          <span>{editedLabel(notes.editedAt, "today")}</span>
                          {notes.final && (
                            <span style={{
                              display: "inline-flex", alignItems: "center", gap: 5, height: 24,
                              padding: "0 9px", borderRadius: 999, background: "#EBF0E1",
                              color: "#2F4417", fontSize: 12.5, fontWeight: 700,
                            }}>
                              <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
                                <path
                                  d="M3.5 5.5V4a2.5 2.5 0 0 1 5 0v1.5M2.5 5.5h7v5h-7z" fill="none"
                                  stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"
                                />
                              </svg>
                              Final
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    <div
                      ref={editorRef}
                      data-notes=""
                      data-testid="notes-editor"
                      contentEditable={!notes.final}
                      suppressContentEditableWarning
                      spellCheck={false}
                      onInput={blocks.onInput}
                      onClick={e => {
                        // A click on an equation opens it at the glyph that
                        // was hit; anything else is a block action.
                        const target = e.target as HTMLElement;
                        const eq = target.closest?.(".math, .imath") as HTMLElement | null;
                        if (eq && !notes.final) {
                          e.preventDefault();
                          e.stopPropagation();
                          const slot = target.closest?.("[data-pos]") as HTMLElement | null;
                          const pos = slot && eq.contains(slot)
                            ? Number(slot.getAttribute("data-pos"))
                            : 0;
                          math.open(eq, pos > 0 ? pos : 0);
                          return;
                        }
                        blocks.onClick(e);
                      }}
                      onMouseUp={selection.show}
                      onKeyUp={selection.show}
                      onKeyDown={e => {
                        // Tab inside a code block indents rather than leaving it.
                        const node = window.getSelection()?.anchorNode;
                        const el = node?.parentElement;
                        if (e.key === "Tab" && el?.closest(".code-ed")) {
                          e.preventDefault();
                          document.execCommand("insertText", false, "  ");
                        }
                      }}
                      aria-label="Notes editor"
                      style={{ minHeight: 600 }}
                    />
                  </>
                )}
              </div>
            </div>

            {math.paletteOpen && math.active && (
              <MathPalette
                left={math.palettePos.left}
                top={math.palettePos.top}
                onInsert={math.insert}
                onDone={math.close}
                preview={math.preview}
              />
            )}

            {selection.bubble && (
              <SelectionBubble
                x={selection.bubble.x}
                y={selection.bubble.y}
                onAsk={selection.ask}
                onExplain={selection.explain}
                onImprove={selection.improve}
                onHighlight={selection.highlight}
              />
            )}
          </section>

          <ClovButton open={clovOpen} onToggle={toggleClov} />

          <ClovPanel
            open={clovOpen}
            onToggle={toggleClov}
            docTitle={docTitle}
            messages={clov.messages}
            busy={clov.busy}
            input={clov.input}
            onInput={clov.setInput}
            quote={clov.quote}
            onClearQuote={() => clov.setQuote(null)}
            onSend={clov.send}
            onAsk={text => clov.ask(text)}
            onClear={clov.clear}
            onInsert={insertReply}
            copied={copied}
            onCopy={(i, text) => {
              void navigator.clipboard?.writeText(text);
              setCopied(i);
              setTimeout(() => setCopied(null), 1500);
            }}
          />
        </div>
        {toast.message && <NotesToast message={toast.message} />}
      </main>
    </FullHeightScreen>
  );
}
