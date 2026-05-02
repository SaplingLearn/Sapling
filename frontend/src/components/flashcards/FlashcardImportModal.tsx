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

  React.useEffect(() => {
    if (open) {
      setCards([]);
      setReverse(false);
      setTab("paste");
      setCourseId(defaultCourseId ?? courses[0]?.course_id ?? "");
      setTopic(defaultTopic ?? "");
    }
  }, [open, defaultCourseId, defaultTopic, courses]);

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
              onClick={() => setTab(t.key)}
              style={{
                padding: "8px 14px", fontSize: 13, fontWeight: tab === t.key ? 600 : 500,
                color: tab === t.key ? "var(--accent)" : "var(--text-dim)",
                background: "transparent",
                borderBottom: tab === t.key ? "2px solid var(--accent)" : "2px solid transparent",
              }}
            >{t.label}</button>
          ))}
        </div>

        {tab === "paste" && <PasteTab cards={cards} onCards={setCards} />}
        {tab === "upload" && <UploadTab onCards={setCards} />}
        {tab === "url" && <UrlTab onCards={setCards} />}
        {tab === "ai" && <AiTab documents={documents} onCards={setCards} />}
        {tab === "photo" && <PhotoTab onCards={setCards} />}

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
