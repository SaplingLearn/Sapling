"use client";
import React from "react";
import Dialog from "../Dialog";
import { CustomSelect } from "../CustomSelect";
import { Icon } from "../Icon";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importCleanup, importCommit, type EnrolledCourse, type ImportCard } from "@/lib/api";
import { courseSelectOptions } from "@/lib/courseSelectOptions";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { CoursePicker } from "../study/CoursePicker";
import type { ParsedCard } from "@/lib/flashcardParsers";
import { PasteTab } from "./tabs/PasteTab";
import { UploadTab } from "./tabs/UploadTab";
import { UrlTab } from "./tabs/UrlTab";
import { AiTab } from "./tabs/AiTab";
import { PhotoTab } from "./tabs/PhotoTab";
import {
  buildFinalCards, cardCountLabel, cleanupPayload, commitBlocker, commitLabel,
  courseLabelOf, flagReason, flaggedCountOf, flaggedLabel, importSummary,
  importedMessage, initialCourseId, isCommitDisabled, numberedCards, patchCard,
  removeCard, validCardsOf,
} from "./importModalModel";
import s from "./FlashcardImportModal.module.css";

type TabKey = "paste" | "upload" | "url" | "ai" | "photo";

interface LibraryDoc { id: string; file_name: string; category?: string }

interface Props {
  open: boolean;
  onClose: () => void;
  courses: EnrolledCourse[];
  defaultCourseId?: string;
  defaultTopic?: string;
  documents: LibraryDoc[];
  /** `documents` is still being read (the page reads it when this opens). */
  documentsLoading?: boolean;
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

/**
 * "Clean up with AI": sends the filled-in rows and replaces the deck with the
 * reply. The reply belongs to the open of the dialog it was asked in: closing
 * the dialog unmounts this, and a reply that lands afterwards is dropped (it
 * used to replace the deck of the NEXT open, #769's race by another door).
 */
function useCleanup(cards: ParsedCard[], onChange: (next: ParsedCard[]) => void) {
  const toast = useToast();
  const { userId } = useUser();
  const [cleaning, setCleaning] = React.useState(false);
  const req = useLatestRequest();

  const cleanup = async () => {
    if (!userId) return;
    const valid = cleanupPayload(cards);
    if (valid.length === 0) { toast.warn("No valid cards to clean up."); return; }
    const run = req.begin();
    setCleaning(true);
    try {
      const res = await importCleanup(userId, valid);
      if (!run.isCurrent()) return;
      onChange(numberedCards(res.cards));
      toast.success("Cleaned up.");
    } catch (err) {
      if (run.isCurrent()) toast.error(`Cleanup failed: ${String(err)}`);
    } finally {
      if (run.isCurrent()) setCleaning(false);
    }
  };

  return { cleaning, cleanup };
}

function ModalHeader({ titleId, onClose }: { titleId: string; onClose: () => void }) {
  return (
    <header className={s.header}>
      <h2 id={titleId} className={`h-serif ${s.title}`}>Import flashcards</h2>
      <button type="button" className={s.close} onClick={onClose} aria-label="Close dialog">
        <Icon name="x" size={16} />
      </button>
    </header>
  );
}

interface SourceInputProps {
  tab: TabKey;
  cards: ParsedCard[];
  onCards: (next: ParsedCard[]) => void;
  documents: LibraryDoc[];
  documentsLoading: boolean;
  /** Receives the Paste textarea: where focus goes when the dialog opens. */
  pasteRef: React.Ref<HTMLTextAreaElement>;
}

/** The active source's own input. Only one is mounted at a time. */
function SourceInput({ tab, cards, onCards, documents, documentsLoading, pasteRef }: SourceInputProps) {
  switch (tab) {
    case "paste": return <PasteTab cards={cards} onCards={onCards} textareaRef={pasteRef} />;
    case "upload": return <UploadTab onCards={onCards} />;
    case "url": return <UrlTab onCards={onCards} />;
    case "ai": return <AiTab documents={documents} documentsLoading={documentsLoading} onCards={onCards} />;
    case "photo": return <PhotoTab onCards={onCards} />;
  }
}

/** Left column: where the cards come from. */
function SourcePane({ onSelect, ...input }: SourceInputProps & { onSelect: (next: TabKey) => void }) {
  return (
    <section className={s.source} aria-label="Card source">
      <div className={`${s.seg} ${s.sourcePicker}`} role="group" aria-label="Import from">
        {TABS.map(t => (
          <button
            key={t.key}
            type="button"
            className={s.segOpt}
            aria-pressed={input.tab === t.key}
            onClick={() => onSelect(t.key)}
          >{t.label}</button>
        ))}
      </div>
      <div className={s.sourceBody} data-source={input.tab}>
        <SourceInput {...input} />
      </div>
    </section>
  );
}

interface PreviewRowProps {
  card: ParsedCard;
  onPatch: (patch: Partial<ParsedCard>) => void;
  onRemove: () => void;
}

function PreviewRow({ card, onPatch, onRemove }: PreviewRowProps) {
  const reason = flagReason(card);
  return (
    <div role="listitem" className={s.row} data-flagged={reason ? "" : undefined}>
      <span className={s.rowNum}>{card.row}</span>
      <input
        className={s.cell}
        value={card.front}
        onChange={e => onPatch({ front: e.target.value })}
        placeholder="Term"
        aria-label={`Term, row ${card.row}`}
      />
      <input
        className={s.cell}
        value={card.back}
        onChange={e => onPatch({ back: e.target.value })}
        placeholder="Definition"
        aria-label={`Definition, row ${card.row}`}
      />
      <button
        type="button"
        className={s.rowRemove}
        onClick={onRemove}
        title="Delete row"
        aria-label={`Delete row ${card.row}`}
      >
        <Icon name="x" size={12} />
      </button>
      {reason && <span className={s.rowReason}>{reason}</span>}
    </div>
  );
}

interface DestinationProps {
  courses: EnrolledCourse[];
  courseId: string;
  onCourse: (next: string) => void;
  topic: string;
  onTopic: (next: string) => void;
}

/**
 * The course field. The shared CoursePicker (dot, code, name, as the page
 * header shows it) whenever the chosen course is one of `courses`. It has no
 * "nothing chosen" state (it shows its first row for a value it does not
 * know, and nothing at all for an empty list), so until a known course is
 * chosen the field is a plain select with a placeholder instead.
 */
function CourseField({ courses, courseId, onCourse }: Pick<DestinationProps, "courses" | "courseId" | "onCourse">) {
  if (courses.some(c => c.course_id === courseId)) {
    return <CoursePicker courses={courses} value={courseId} onChange={onCourse} fullWidth />;
  }
  return (
    <CustomSelect
      className={`${s.select} ${s.selectFill} ${s.selectLg}`}
      value={courseId}
      onChange={onCourse}
      placeholder="Pick a course…"
      options={courseSelectOptions(courses)}
    />
  );
}

/** Where the cards go: the first row of the right column. */
function Destination({ courses, courseId, onCourse, topic, onTopic }: DestinationProps) {
  const courseLabelId = React.useId();
  const topicId = React.useId();
  return (
    <div className={s.dest}>
      <div className={`${s.field} ${s.fieldCourse}`} role="group" aria-labelledby={courseLabelId}>
        <span id={courseLabelId} className="label-micro">Course</span>
        <div className={s.pickerSlot}>
          <CourseField courses={courses} courseId={courseId} onCourse={onCourse} />
        </div>
      </div>
      <div className={`${s.field} ${s.fieldTopic}`}>
        <label htmlFor={topicId} className="label-micro">Topic</label>
        <input
          id={topicId}
          className={`${s.input} ${s.inputLg}`}
          value={topic}
          onChange={e => onTopic(e.target.value)}
          placeholder="e.g. Recursion"
        />
      </div>
    </div>
  );
}

interface PreviewPaneProps {
  cards: ParsedCard[];
  onChange: (next: ParsedCard[]) => void;
  reverse: boolean;
  onReverse: (next: boolean) => void;
  destination: DestinationProps;
}

/** Right column: where the cards go, then what they are. */
function PreviewPane({ cards, onChange, reverse, onReverse, destination }: PreviewPaneProps) {
  const { cleaning, cleanup } = useCleanup(cards, onChange);
  const flagged = flaggedCountOf(cards);

  return (
    <section className={s.preview} aria-label="Cards to import">
      <Destination {...destination} />
      <div className={s.previewHead}>
        <p className={s.count}>
          <span className={s.countCards}>{cardCountLabel(cards.length - flagged)}</span>
          {flagged > 0 && <span className={s.countFlagged}>{flaggedLabel(flagged)}</span>}
        </p>
        <div className={s.previewActions}>
          <label className={s.reverse}>
            <input type="checkbox" checked={reverse} onChange={e => onReverse(e.target.checked)} />
            Generate reverse cards
          </label>
          <button type="button" className="btn btn--sm" onClick={cleanup} disabled={cleaning || cards.length === 0}>
            <Icon name="sparkle" size={11} /> {cleaning ? "Cleaning…" : "Clean up with AI"}
          </button>
        </div>
      </div>

      {cards.length === 0 ? (
        <p className={s.empty}>Cards show up here as you add them.</p>
      ) : (
        <div role="list" className={s.rows}>
          {cards.map((card, i) => (
            <PreviewRow
              key={i}
              card={card}
              onPatch={patch => onChange(patchCard(cards, i, patch))}
              onRemove={() => onChange(removeCard(cards, i))}
            />
          ))}
        </div>
      )}
    </section>
  );
}

interface ImportFooterProps {
  summary: string;
  onClose: () => void;
  onCommit: () => void;
  commitDisabled: boolean;
  commitText: string;
}

/** What Import will do, in words, and the two ways out. */
function ImportFooter({ summary, onClose, onCommit, commitDisabled, commitText }: ImportFooterProps) {
  return (
    <footer className={s.footer}>
      <p className={s.summary}>{summary}</p>
      <div className={s.actions}>
        <button type="button" className={`btn btn--ghost ${s.action}`} onClick={onClose}>Cancel</button>
        <button
          type="button"
          className={`btn btn--primary ${s.action}`}
          onClick={onCommit}
          disabled={commitDisabled}
        >
          {commitText}
        </button>
      </div>
    </footer>
  );
}

export function FlashcardImportModal({
  open, onClose, courses, defaultCourseId, defaultTopic, documents, documentsLoading = false, onImported,
}: Props) {
  const {
    tab, selectTab, cards, setCards, onTabCards, reverse, setReverse,
    courseId, setCourseId, topic, setTopic,
  } = useImportSession(open, courses, defaultCourseId, defaultTopic);
  const finalCards = useFinalCards(cards, reverse);
  const { committing, commit } = useCommit(courseId, topic, finalCards, onImported, onClose);
  const titleId = React.useId();
  // The dialog always opens on Paste, so its textarea is where typing starts.
  const pasteRef = React.useRef<HTMLTextAreaElement>(null);

  // Dialog draws the paper, traps focus and handles Escape / backdrop / scroll
  // lock. Its own title and close button are switched off so the header below
  // can lay them out; `labelledBy` keeps the dialog named by that title.
  return (
    <Dialog
      open={open}
      onClose={onClose}
      labelledBy={titleId}
      width="min(980px, calc(100vw - 32px))"
      padding="0"
      showCloseButton={false}
      initialFocusRef={pasteRef}
    >
      <div className={s.frame}>
        <ModalHeader titleId={titleId} onClose={onClose} />
        <div className={s.body}>
          <SourcePane
            tab={tab}
            onSelect={selectTab}
            cards={cards}
            onCards={onTabCards}
            documents={documents}
            documentsLoading={documentsLoading}
            pasteRef={pasteRef}
          />
          <PreviewPane
            cards={cards}
            onChange={setCards}
            reverse={reverse}
            onReverse={setReverse}
            destination={{ courses, courseId, onCourse: setCourseId, topic, onTopic: setTopic }}
          />
        </div>
        <ImportFooter
          summary={importSummary(finalCards.length, courseLabelOf(courses, courseId), !!courseId, topic)}
          onClose={onClose}
          onCommit={commit}
          commitDisabled={isCommitDisabled(committing, finalCards.length, courseId, topic)}
          commitText={commitLabel(committing, finalCards.length)}
        />
      </div>
    </Dialog>
  );
}
