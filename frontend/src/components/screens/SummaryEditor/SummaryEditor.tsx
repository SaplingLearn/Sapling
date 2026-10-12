"use client";
import React from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Link from "next/link";

import { useUser } from "@/context/UserContext";
import { useToast } from "../../ToastProvider";
import {
  getSummaryDoc,
  updateSummaryDocContent,
  keepSummaryDocSuggestion,
  undoSummaryDocSuggestion,
} from "@/lib/api";
import type { SummaryDoc, SummaryDocSuggestion } from "@/lib/types";
import { SuggestionMark } from "@/lib/summaryEditor/suggestionMark";
import { SuggestionDecorations, type PendingSuggestionWidget } from "@/lib/summaryEditor/suggestionDecorations";
import { SourcesPanel } from "./SourcesPanel";
import { HistoryPanel } from "./HistoryPanel";

function prosemirrorDocFromText(text: string): Record<string, unknown> {
  const paragraphs = text.split("\n\n").map((p) => p.trim()).filter(Boolean);
  return {
    type: "doc",
    content: paragraphs.map((p) => ({
      type: "paragraph",
      content: [{ type: "text", text: p }],
    })),
  };
}

type SaveState = "idle" | "saving" | "saved" | "error";
type AskTarget = { from: number; to: number; text: string } | null;

export interface SummaryEditorProps {
  summaryDocId: string;
}

export function SummaryEditor({ summaryDocId }: SummaryEditorProps) {
  const { userId, userReady } = useUser();
  const toast = useToast();
  const [doc, setDoc] = React.useState<SummaryDoc | null>(null);
  const [rightTab, setRightTab] = React.useState<"sources" | "history">("sources");
  const [pendingSuggestions, setPendingSuggestions] = React.useState<SummaryDocSuggestion[]>([]);
  const [saveState, setSaveState] = React.useState<SaveState>("idle");
  const [askTarget, setAskTarget] = React.useState<AskTarget>(null);
  const [askInstruction, setAskInstruction] = React.useState("");
  const [asking, setAsking] = React.useState(false);
  // Spec section 3 "Suggestion scope" — only meaningful for a selection
  // ask (a whole-doc ask has no "surrounding text" to protect), and
  // defaults off (confined to the highlight, the safer default).
  const [allowSurroundingEdits, setAllowSurroundingEdits] = React.useState(false);
  const autosaveTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const editor = useEditor({
    extensions: [StarterKit, SuggestionMark, SuggestionDecorations],
    content: { type: "doc", content: [] },
    onUpdate: ({ editor: e }) => scheduleAutosave(e.getJSON() as Record<string, unknown>),
    onSelectionUpdate: ({ editor: e }) => {
      const { from, to, empty } = e.state.selection;
      if (empty) {
        setAskTarget(null);
        return;
      }
      setAskTarget({ from, to, text: e.state.doc.textBetween(from, to, " ") });
    },
  });

  const load = React.useCallback(async () => {
    if (!userId) return;
    try {
      const d = await getSummaryDoc(summaryDocId, userId);
      setDoc(d);
      setPendingSuggestions(d.pending_suggestions);
    } catch (err) {
      toast.error(`Couldn't load this summary: ${String((err as Error)?.message || err)}`);
    }
  }, [summaryDocId, userId, toast]);

  React.useEffect(() => {
    if (userReady && userId) load();
  }, [userReady, userId, load]);

  // Keyed on doc.id, not the doc object itself: `doc` is replaced wholesale
  // after every Keep/Undo (setDoc merges in the mutation response), and
  // re-running setContent then would stomp whatever the user typed in the
  // editor between that mutation's request and response — the editor is
  // already the source of truth for content once loaded once.
  const loadedDocIdRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (editor && doc && loadedDocIdRef.current !== doc.id) {
      editor.commands.setContent(doc.content, false);
      loadedDocIdRef.current = doc.id;
    }
  }, [editor, doc]);

  const scheduleAutosave = React.useCallback(
    (content: Record<string, unknown>) => {
      if (!doc || !userId) return;
      setSaveState("saving");
      if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
      autosaveTimer.current = setTimeout(async () => {
        try {
          await updateSummaryDocContent(doc.id, userId, content);
          setSaveState("saved");
        } catch {
          setSaveState("error");
        }
      }, 1200);
    },
    [doc, userId],
  );

  const keepSuggestion = React.useCallback(
    async (s: SummaryDocSuggestion) => {
      if (!editor || !doc || !userId) return;
      if (s.anchor_from !== null && s.anchor_to !== null) {
        // Known v1 gap (see the plan's "known simplification" note): this
        // only catches THIS suggestion's own anchor going stale.
        // anchor_from/anchor_to for every OTHER pending suggestion are
        // static ints, never remapped through ProseMirror's transaction
        // mapping as the doc changes — so keeping/editing ahead of a later
        // suggestion's anchor can make ITS textBetween read the wrong
        // (shifted) span and get dropped as "changed" even though it
        // wasn't. Fails safe (never misapplies text), just a potentially
        // confusing false positive with multiple suggestions in flight.
        const currentText = editor.state.doc.textBetween(s.anchor_from, s.anchor_to, " ");
        if (currentText !== (s.original_text ?? "")) {
          toast.info("This part changed since the suggestion was made — ask again.");
          setPendingSuggestions((prev) => prev.filter((p) => p.id !== s.id));
          return;
        }
        editor.chain().insertContentAt({ from: s.anchor_from, to: s.anchor_to }, s.proposed_text).run();
      } else {
        // Known v1 gap: unlike the anchored path above, a whole-doc
        // suggestion has no captured "original text" to diff against (a
        // whole-doc ask has no selection, so original_text is always
        // null) — so this path has no staleness guard at all. Keeping a
        // whole-doc suggestion always replaces the entire document with
        // the agent's rewrite, discarding any edits made since the ask
        // and any formatting split("\n\n") can't reconstruct.
        editor.commands.setContent(prosemirrorDocFromText(s.proposed_text));
      }
      const content = editor.getJSON() as Record<string, unknown>;
      try {
        const updated = await keepSummaryDocSuggestion(doc.id, userId, s.id, content);
        setDoc((prev) => (prev ? { ...prev, ...updated } : prev));
        setPendingSuggestions((prev) => prev.filter((p) => p.id !== s.id));
      } catch (err) {
        toast.error(`Couldn't save that change: ${String((err as Error)?.message || err)}`);
      }
    },
    [editor, doc, userId, toast],
  );

  const undoSuggestionLocal = React.useCallback(
    async (s: SummaryDocSuggestion) => {
      if (!editor || !doc || !userId) return;
      if (s.anchor_from !== null && s.anchor_to !== null) {
        editor.chain().setTextSelection({ from: s.anchor_from, to: s.anchor_to }).unsetSuggestionMark().run();
      }
      try {
        await undoSummaryDocSuggestion(doc.id, userId, s.id);
      } catch (err) {
        toast.error(`Couldn't undo that: ${String((err as Error)?.message || err)}`);
      } finally {
        setPendingSuggestions((prev) => prev.filter((p) => p.id !== s.id));
      }
    },
    [editor, doc, userId, toast],
  );

  // Rebuild the decoration plugin's widget list whenever pending
  // suggestions change, then force a redraw (no-op transaction) —
  // decorations are derived from `storage.pending`, not from the document
  // itself, so ProseMirror won't recompute them on its own.
  React.useEffect(() => {
    if (!editor) return;
    const storage = editor.storage.summarySuggestionDecorations as { pending: PendingSuggestionWidget[] };
    storage.pending = pendingSuggestions
      .filter((s) => s.anchor_from !== null && s.anchor_to !== null && s.status === "pending")
      .map((s) => ({
        id: s.id,
        from: s.anchor_from as number,
        to: s.anchor_to as number,
        proposedText: s.proposed_text,
        onKeep: () => keepSuggestion(s),
        onUndo: () => undoSuggestionLocal(s),
      }));
    editor.view.dispatch(editor.state.tr);
  }, [editor, pendingSuggestions, keepSuggestion, undoSuggestionLocal]);

  const wholeDocSuggestions = pendingSuggestions.filter((s) => s.anchor_from === null);

  const submitAsk = async () => {
    if (!doc || !userId || !askInstruction.trim()) return;
    setAsking(true);
    try {
      const { askSummaryDocAgent } = await import("@/lib/api");
      const suggestion = await askSummaryDocAgent(doc.id, userId, {
        instruction: askInstruction.trim(),
        anchor_from: askTarget?.from ?? null,
        anchor_to: askTarget?.to ?? null,
        original_text: askTarget?.text ?? null,
        allow_surrounding_edits: askTarget ? allowSurroundingEdits : false,
      });
      setPendingSuggestions((prev) => [...prev, suggestion]);
      if (askTarget) {
        editor?.chain().setTextSelection(askTarget).setSuggestionMark(suggestion.id).run();
      }
      setAskInstruction("");
      setAskTarget(null);
      setAllowSurroundingEdits(false);
    } catch (err) {
      toast.error(`Couldn't get a suggestion: ${String((err as Error)?.message || err)}`);
    } finally {
      setAsking(false);
    }
  };

  if (!doc) {
    return <div style={{ padding: 40 }}>Loading…</div>;
  }

  return (
    <div style={{ display: "flex", height: "100%" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <header style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "16px 24px", borderBottom: "1px solid var(--border)",
        }}>
          <Link href="/library" className="btn btn--ghost btn--sm">← Back to Library</Link>
          <span className="label-micro" data-testid="summary-editor-save-state">
            {saveState === "saving" ? "Saving…" : saveState === "error" ? "Couldn't save — keep typing to retry" : "Saved"}
          </span>
        </header>
        <div style={{ flex: 1, overflowY: "auto", padding: 24 }} data-testid="summary-editor-content">
          {wholeDocSuggestions.map((s) => (
            <div key={s.id} className="summary-suggestion-card" style={{ display: "flex", marginBottom: 16 }}>
              <span className="summary-suggestion-card__text">{s.proposed_text}</span>
              <span className="summary-suggestion-card__actions">
                <button type="button" className="btn btn--sm btn--primary" onClick={() => keepSuggestion(s)}>Keep it</button>
                <button type="button" className="btn btn--sm btn--ghost" onClick={() => undoSuggestionLocal(s)}>Undo this</button>
              </span>
            </div>
          ))}
          <div className="body-serif">
            <EditorContent editor={editor} />
          </div>
        </div>
        <div style={{ padding: "12px 24px", borderTop: "1px solid var(--border)" }}>
          {askTarget && (
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>
              <input
                type="checkbox"
                checked={allowSurroundingEdits}
                onChange={(e) => setAllowSurroundingEdits(e.target.checked)}
              />
              Let it adjust nearby text too, if that helps it flow
            </label>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="mock-input"
              style={{ flex: 1 }}
              placeholder={askTarget ? "Ask about the selected text…" : "Ask about this doc…"}
              value={askInstruction}
              onChange={(e) => setAskInstruction(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitAsk();
              }}
              data-testid="summary-editor-ask-input"
            />
            <button
              type="button"
              className="btn btn--primary btn--sm"
              disabled={asking || !askInstruction.trim()}
              onClick={submitAsk}
            >
              Ask
            </button>
          </div>
        </div>
      </div>
      <aside style={{ width: 280, borderLeft: "1px solid var(--border)", flexShrink: 0, padding: 16, overflowY: "auto" }}>
        <div style={{ display: "flex", gap: 4, marginBottom: 12 }}>
          <button
            type="button"
            className={`btn btn--sm ${rightTab === "sources" ? "btn--primary" : "btn--ghost"}`}
            onClick={() => setRightTab("sources")}
          >
            Sources
          </button>
          <button
            type="button"
            className={`btn btn--sm ${rightTab === "history" ? "btn--primary" : "btn--ghost"}`}
            onClick={() => setRightTab("history")}
          >
            History
          </button>
        </div>
        {rightTab === "sources" ? (
          <SourcesPanel doc={doc} userId={userId!} onDocChanged={setDoc} />
        ) : (
          <HistoryPanel
            summaryDocId={doc.id}
            userId={userId!}
            onDocChanged={(updated) => setDoc((prev) => (prev ? { ...prev, ...updated } : prev))}
          />
        )}
      </aside>
    </div>
  );
}
