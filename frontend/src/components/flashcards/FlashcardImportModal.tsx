"use client";
import React from "react";
import Dialog from "../Dialog";
import { CustomSelect } from "../CustomSelect";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importCommit, type EnrolledCourse } from "@/lib/api";
import { isValid, type ParsedCard } from "@/lib/flashcardParsers";
import { ParsedCardsTable } from "./ParsedCardsTable";
import { PasteTab } from "./tabs/PasteTab";
import { UploadTab } from "./tabs/UploadTab";
import { UrlTab } from "./tabs/UrlTab";
import { AiTab } from "./tabs/AiTab";
import { PhotoTab } from "./tabs/PhotoTab";

type TabKey = "paste" | "upload" | "url" | "ai" | "photo";

interface LibraryDoc { id: string; file_name: string; category?: string }

interface Props {
  open: boolean;
  onClose: () => void;
  courses: EnrolledCourse[];
  defaultCourseId?: string;
  defaultTopic?: string;
  documents: LibraryDoc[];
  onImported: (count: number) => void;
}

const TABS: { key: TabKey; label: string }[] = [
  { key: "paste", label: "Paste" },
  { key: "upload", label: "Upload" },
  { key: "url", label: "URL" },
  { key: "ai", label: "AI" },
  { key: "photo", label: "Photo" },
];

export function FlashcardImportModal({
  open, onClose, courses, defaultCourseId, defaultTopic, documents, onImported,
}: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [tab, setTab] = React.useState<TabKey>("paste");
  const [cards, setCards] = React.useState<ParsedCard[]>([]);
  const [reverse, setReverse] = React.useState(false);
  const [courseId, setCourseId] = React.useState<string>(defaultCourseId ?? courses[0]?.course_id ?? "");
  const [topic, setTopic] = React.useState<string>(defaultTopic ?? "");
  const [committing, setCommitting] = React.useState(false);

  // Request scope (#769). Every tab switch and every open starts a new scope;
  // a tab's async import (URL fetch, AI generate, OCR, cloze…) writes the
  // shared deck only if it resolves inside the scope it started in. Without
  // this, a request from a tab you left — or from before the modal was
  // closed and reopened — landed late and overwrote the deck on screen. A
  // monotonic counter (not the tab name) so leaving and re-entering a tab
  // doesn't revive the old tab's request.
  const [scope, setScope] = React.useState(0);
  const scopeRef = React.useRef(scope);
  React.useLayoutEffect(() => { scopeRef.current = scope; }, [scope]);
  const onTabCards = React.useCallback((next: ParsedCard[]) => {
    if (scopeRef.current === scope) setCards(next);
  }, [scope]);
  const selectTab = (next: TabKey) => {
    if (next === tab) return;
    setTab(next);
    setScope(s => s + 1);
  };

  // Reset on the open TRANSITION only (#769). The old effect also keyed on
  // `courses`/defaults, so a parent re-render that rebuilt the courses array
  // wiped the deck mid-edit. Adjusted during render (the Study.tsx
  // StudyModePanel pattern) so the reset lands with the opening render.
  const [wasOpen, setWasOpen] = React.useState(false);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setCards([]);
      setReverse(false);
      setTab("paste");
      setCourseId(defaultCourseId ?? courses[0]?.course_id ?? "");
      setTopic(defaultTopic ?? "");
      setScope(s => s + 1);
    }
  }
  // Courses that arrive AFTER opening still fill an empty pick — filling a
  // blank never touches the deck, unlike the old full reset.
  const fallbackCourseId = defaultCourseId ?? courses[0]?.course_id ?? "";
  if (open && !courseId && fallbackCourseId) setCourseId(fallbackCourseId);

  const validCards = cards.filter(isValid);
  const finalCards = React.useMemo(() => {
    const base = validCards.map(c => ({ front: c.front, back: c.back }));
    if (!reverse) return base;
    return base.flatMap(c => [c, { front: c.back, back: c.front }]);
  }, [validCards, reverse]);

  const commit = async () => {
    if (!userId) return;
    if (!courseId) { toast.warn("Pick a course first."); return; }
    if (!topic.trim()) { toast.warn("Add a topic name."); return; }
    if (finalCards.length === 0) { toast.warn("No valid cards to import."); return; }
    setCommitting(true);
    try {
      const res = await importCommit(userId, courseId, topic.trim(), finalCards, true);
      const skipNote = res.skipped_duplicates > 0
        ? ` ${res.skipped_duplicates} skipped (duplicates).`
        : "";
      toast.success(`Imported ${res.inserted} card${res.inserted === 1 ? "" : "s"}.${skipNote}`);
      onImported(res.inserted);
      onClose();
    } catch (err) {
      toast.error(`Import failed: ${String(err)}`);
    } finally {
      setCommitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Import flashcards" size="xl">
      <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: 4 }}>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <div style={{ minWidth: 220 }}>
            <div className="label-micro">Course</div>
            <CustomSelect
              ariaLabel="Course"
              value={courseId}
              onChange={setCourseId}
              placeholder="Pick a course…"
              options={courses.map(c => ({
                value: c.course_id,
                label: c.course_code || c.course_name,
                description: c.course_code ? c.course_name : undefined,
              }))}
            />
          </div>
          <div style={{ minWidth: 220, flex: 1 }}>
            <div className="label-micro">Topic / set name</div>
            <input
              value={topic}
              onChange={e => setTopic(e.target.value)}
              placeholder="e.g. Cell Biology — Chapter 5"
              style={{ width: "100%", padding: 8, borderRadius: "var(--r-md)", background: "var(--bg-panel)", border: "1px solid var(--border)", color: "var(--text)" }}
            />
          </div>
        </div>

        <div style={{ display: "flex", borderBottom: "1px solid var(--border)" }}>
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => selectTab(t.key)}
              style={{
                padding: "8px 14px", fontSize: 13, fontWeight: tab === t.key ? 600 : 500,
                color: tab === t.key ? "var(--accent)" : "var(--text-dim)",
                background: "transparent",
                borderBottom: tab === t.key ? "2px solid var(--accent)" : "2px solid transparent",
              }}
            >{t.label}</button>
          ))}
        </div>

        {tab === "paste" && <PasteTab cards={cards} onCards={onTabCards} />}
        {tab === "upload" && <UploadTab onCards={onTabCards} />}
        {tab === "url" && <UrlTab onCards={onTabCards} />}
        {tab === "ai" && <AiTab documents={documents} onCards={onTabCards} />}
        {tab === "photo" && <PhotoTab onCards={onTabCards} />}

        <ParsedCardsTable
          cards={cards}
          onChange={setCards}
          reverseEnabled={reverse}
          onReverseToggle={setReverse}
        />

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 6 }}>
          <button className="btn btn--sm" onClick={onClose}>Cancel</button>
          <button
            className="btn btn--sm btn--primary"
            onClick={commit}
            disabled={committing || finalCards.length === 0 || !courseId || !topic.trim()}
          >
            {committing ? "Importing…" : `Import ${finalCards.length} card${finalCards.length === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
