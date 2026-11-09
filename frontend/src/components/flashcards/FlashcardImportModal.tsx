"use client";
import React from "react";
import Dialog from "../Dialog";
import { CustomSelect } from "../CustomSelect";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importCommit, type EnrolledCourse, type ImportCard } from "@/lib/api";
import type { ParsedCard } from "@/lib/flashcardParsers";
import { ParsedCardsTable } from "./ParsedCardsTable";
import { PasteTab } from "./tabs/PasteTab";
import { UploadTab } from "./tabs/UploadTab";
import { UrlTab } from "./tabs/UrlTab";
import { AiTab } from "./tabs/AiTab";
import { PhotoTab } from "./tabs/PhotoTab";
import {
  buildFinalCards, commitBlocker, commitLabel, courseOptions, importedMessage,
  initialCourseId, isCommitDisabled, tabButtonStyle, validCardsOf,
} from "./importModalModel";

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

/** Tab, deck, reverse, course and topic state for one open of the modal. */
function useImportSession(
  open: boolean,
  courses: EnrolledCourse[],
  defaultCourseId: string | undefined,
  defaultTopic: string | undefined,
) {
  const [tab, setTab] = React.useState<TabKey>("paste");
  const [cards, setCards] = React.useState<ParsedCard[]>([]);
  const [reverse, setReverse] = React.useState(false);
  const [courseId, setCourseId] = React.useState<string>(initialCourseId(defaultCourseId, courses));
  const [topic, setTopic] = React.useState<string>(defaultTopic ?? "");

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
      setCourseId(initialCourseId(defaultCourseId, courses));
      setTopic(defaultTopic ?? "");
      setScope(s => s + 1);
    }
  }
  // Courses that arrive AFTER opening still fill an empty pick — filling a
  // blank never touches the deck, unlike the old full reset.
  const fallbackCourseId = initialCourseId(defaultCourseId, courses);
  if (open && !courseId && fallbackCourseId) setCourseId(fallbackCourseId);

  return {
    tab, selectTab, cards, setCards, onTabCards, reverse, setReverse,
    courseId, setCourseId, topic, setTopic,
  };
}

function useFinalCards(cards: ParsedCard[], reverse: boolean): ImportCard[] {
  const validCards = validCardsOf(cards);
  return React.useMemo(() => buildFinalCards(validCards, reverse), [validCards, reverse]);
}

function useCommit(
  courseId: string,
  topic: string,
  finalCards: ImportCard[],
  onImported: (count: number) => void,
  onClose: () => void,
) {
  const toast = useToast();
  const { userId } = useUser();
  const [committing, setCommitting] = React.useState(false);

  const commit = async () => {
    if (!userId) return;
    const blocker = commitBlocker(courseId, topic, finalCards.length);
    if (blocker) { toast.warn(blocker); return; }
    setCommitting(true);
    try {
      const res = await importCommit(userId, courseId, topic.trim(), finalCards, true);
      toast.success(importedMessage(res));
      onImported(res.inserted);
      onClose();
    } catch (err) {
      toast.error(`Import failed: ${String(err)}`);
    } finally {
      setCommitting(false);
    }
  };

  return { committing, commit };
}

export function FlashcardImportModal({
  open, onClose, courses, defaultCourseId, defaultTopic, documents, onImported,
}: Props) {
  const {
    tab, selectTab, cards, setCards, onTabCards, reverse, setReverse,
    courseId, setCourseId, topic, setTopic,
  } = useImportSession(open, courses, defaultCourseId, defaultTopic);
  const finalCards = useFinalCards(cards, reverse);
  const { committing, commit } = useCommit(courseId, topic, finalCards, onImported, onClose);

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
              options={courseOptions(courses)}
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
              style={tabButtonStyle(tab === t.key)}
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
            disabled={isCommitDisabled(committing, finalCards.length, courseId, topic)}
          >
            {commitLabel(committing, finalCards.length)}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
