"use client";
import React from "react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { StudyNavigation } from "../fa26/Navigation";
import { TopBar } from "../TopBar";
import { AIDisclaimerChip } from "../chat/AIDisclaimerChip";
import { Icon } from "../Icon";
import { FilterPills } from "@/components/ui";

// Lazy-load to keep mermaid/katex/highlight.js out of the OpenNext
// server bundle. See ChatPanel.tsx for the rationale.
const MarkdownChat = dynamic(
  () => import("../chat/MarkdownChat").then((m) => m.MarkdownChat),
  { ssr: false, loading: () => null },
);

// Lazy-load the framer-motion subtree the same way (#111) — the library is
// only needed for the toggle highlight + mode crossfade, so it stays out of
// Study's initial bundle. Fallbacks keep the resting visuals identical while
// the chunk loads: an identically-styled static pill, and the same flex
// wrapper minus the crossfade.
// The mode transition wraps the pane CONTENT, so it must not depend on the
// motion chunk (#490 review): a lazy wrapper either gates the panes behind
// the chunk fetch (next/dynamic's fallback can't carry children) or remounts
// them mid-session when the chunk lands, wiping state. A keyed CSS
// enter-fade needs no chunk at all; the global reduced-motion reset covers
// it. The render-phase state derivation mirrors the old AnimatePresence
// initial={false} — no animation on first mount, only on mode switches.
function StudyModePanel({ mode, children }: { mode: string; children: React.ReactNode }) {
  const [seen, setSeen] = React.useState({ mode, animate: false });
  if (seen.mode !== mode) setSeen({ mode, animate: true });
  return (
    <div
      key={mode}
      className={seen.animate ? "study-mode-enter" : undefined}
      style={{ display: "flex", flex: 1, minHeight: 0 }}
    >
      {children}
    </div>
  );
}
import { FlashcardsSkeleton } from "../Skeleton";
import { useToast } from "../ToastProvider";
import { useIsMobile } from "@/lib/useIsMobile";
import { extractErrorDetail, humanizeError } from "@/lib/errorMessage";
import { useUser } from "@/context/UserContext";
import { useActiveSemester, courseInTerm } from "@/lib/useActiveSemester";
import {
  getCourses,
  getFlashcards,
  generateFlashcards,
  rateFlashcard,
  deleteFlashcard,
  getDocuments,
  type EnrolledCourse,
} from "@/lib/api";
import { FlashcardImportModal } from "../flashcards/FlashcardImportModal";
import { StudyPlans } from "../study/StudyPlans";
import { DueQueue } from "../learn/DueQueue";
import { RetentionCheck } from "../learn/RetentionCheck";
import { useLoopStatus } from "../learn/useLoopStatus";

type Mode = "guide" | "cards";

type RawCard = {
  id: string;
  topic?: string;
  front: string;
  back: string;
};

const ratingOptions: { n: number; label: string; color: string; emoji: string; hint: string }[] = [
  { n: 1, label: "forgot", color: "var(--err)", emoji: "🙈", hint: "1" },
  { n: 2, label: "hard", color: "var(--warn)", emoji: "🤔", hint: "2" },
  { n: 3, label: "easy", color: "var(--accent)", emoji: "✨", hint: "3" },
];

export function Study() {
  const isMobile = useIsMobile();
  const { userId, userReady } = useUser();
  const searchParams = useSearchParams();
  const [mode, setMode] = React.useState<Mode>(
    searchParams.get("mode") === "cards" ? "cards" : "guide",
  );
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const planCourseId = searchParams.get("course") || "";
  const [activeSemester, , semesterHydrated] = useActiveSemester();

  React.useEffect(() => {
    if (!userReady || !userId) return;
    getCourses(userId)
      .then(r => setCourses(r.courses || []))
      .catch(err => console.error("study courses load failed", err));
  }, [userReady, userId]);

  // Flashcards retain their existing semester behavior. The assessment guide
  // treats all enrolled courses as active and always receives the full list.
  const scopedCourses = React.useMemo(
    () => (activeSemester ? courses.filter(c => courseInTerm(c, activeSemester)) : courses),
    [courses, activeSemester],
  );

  const actions = <AIDisclaimerChip />;

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100%" }}>
      <TopBar
        title="Study"
        subtitle={mode === "guide" ? "Your guide, topics and study schedule in one place" : "Spaced review with ratings and a 3D flip"}
        actions={actions}
      />
      <div className="fa26-study-header"><span>Study from your course material</span><StudyNavigation active={mode} onSelect={setMode} /></div>
      <StudyModePanel mode={mode}>
        {mode === "guide" ? (
          <StudyPlans courses={courses} initialCourseId={planCourseId} initialDocumentId={searchParams.get("document") || ""} />
        ) : (
          <FlashcardsMode
            courses={scopedCourses}
            isMobile={isMobile}
            semester={activeSemester}
            semesterReady={semesterHydrated}
          />
        )}
      </StudyModePanel>
    </div>
  );
}

// ── Flashcards mode ──────────────────────────────────────────────────────────

function FlashcardsMode({
  courses,
  isMobile,
  semester,
  semesterReady,
}: {
  courses: EnrolledCourse[];
  isMobile: boolean;
  // As with the assessment guide: "" = All semesters (unscoped); fetches gate on
  // semesterReady so a stored term never double-fetches (#141).
  semester: string;
  semesterReady: boolean;
}) {
  const toast = useToast();
  const retentionCourse = useSearchParams().get("retention-course") ?? "";
  const { userId, userReady } = useUser();
  const [cards, setCards] = React.useState<RawCard[]>([]);
  const [courseId, setCourseId] = React.useState<string>("all");
  const [topicFilter, setTopicFilter] = React.useState<string>("all");
  const [idx, setIdx] = React.useState(0);
  const [flipped, setFlipped] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [docsUsed, setDocsUsed] = React.useState<number | null>(null);
  const [importOpen, setImportOpen] = React.useState(false);
  const [docs, setDocs] = React.useState<{ id: string; file_name: string; category?: string }[]>([]);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  // A failed status read is not an inactive learning loop: retain the legacy
  // flashcards and offer a retry so the student can still reach due reviews.
  const { status: loopActive, retry: retryLoopStatus } = useLoopStatus(userId, userReady);

  React.useEffect(() => {
    if (!userId) return;
    getDocuments(userId)
      .then(r => setDocs(r.documents || []))
      .catch(() => setDocs([]));
  }, [userId]);

  const load = React.useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setLoadError(null);
    try {
      const res = await getFlashcards(userId, undefined, semester || undefined);
      setCards(res.flashcards || []);
      setIdx(0);
      setFlipped(false);
    } catch (err) {
      setLoadError(extractErrorDetail(err).detail || "Couldn't load your flashcards. Please try again.");
      setCards([]);
    } finally {
      setLoading(false);
    }
  }, [userId, semester]);

  React.useEffect(() => {
    if (semesterReady) load();
  }, [load, semesterReady]);

  const topics = React.useMemo(() => {
    const set = new Set<string>();
    for (const c of cards) { if (c.topic) set.add(c.topic); }
    return Array.from(set).sort();
  }, [cards]);

  const filtered = React.useMemo(() => {
    let out = cards;
    if (courseId !== "all") {
      const course = courses.find(c => c.course_id === courseId);
      const courseName = course?.course_name;
      if (courseName) out = out.filter(c => (c.topic || "").toLowerCase().includes(courseName.toLowerCase()));
    }
    if (topicFilter !== "all") out = out.filter(c => c.topic === topicFilter);
    return out;
  }, [cards, courseId, topicFilter, courses]);

  React.useEffect(() => {
    if (idx >= filtered.length) setIdx(0);
    setFlipped(false);
  }, [filtered.length, idx]);

  const card = filtered[idx];

  const rate = React.useCallback(async (r: number) => {
    if (!card) return;
    try {
      await rateFlashcard(userId, card.id, r);
    } catch (err) {
      console.error("rate failed", err);
    }
    setFlipped(false);
    setIdx(i => (filtered.length === 0 ? 0 : (i + 1) % filtered.length));
  }, [card, userId, filtered.length]);

  const remove = React.useCallback(async () => {
    if (!card) return;
    try {
      await deleteFlashcard(userId, card.id);
      toast.success("Card deleted");
      await load();
    } catch (err) {
      console.error("flashcard delete failed", err);
      toast.error(humanizeError(err, "Couldn't delete that card."));
    }
  }, [card, userId, toast, load]);

  // Keyboard: Space flips; 1/2/3 rate when flipped.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (e.code === "Space") { e.preventDefault(); setFlipped(f => !f); return; }
      if (!flipped || !card) return;
      if (e.key === "1") rate(1);
      else if (e.key === "2") rate(2);
      else if (e.key === "3") rate(3);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [flipped, rate, card]);

  const generate = async () => {
    if (!userId) return;
    const course = courses.find(c => c.course_id === courseId);
    const topic = course ? course.course_name : (topicFilter !== "all" ? topicFilter : "");
    if (!topic) {
      toast.warn("Pick a course or topic before generating.");
      return;
    }
    setGenerating(true);
    setDocsUsed(null);
    try {
      // Term-scoped generation context: the selected term's course documents.
      const r = await generateFlashcards(userId, topic, 5, semester || undefined);
      setDocsUsed(r.context_used?.documents_found ?? 0);
      await load();
      toast.success(`Added ${r.flashcards.length} new card${r.flashcards.length === 1 ? "" : "s"}.`);
    } catch (err) {
      console.error("flashcard generate failed", err);
      toast.error(humanizeError(err, "Couldn't generate cards right now."));
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {loopActive === true && <DueQueue userId={userId} courseId={courseId !== "all" ? courseId : undefined} />}
        {loopActive === true && <RetentionCheck key={userId} userId={userId} courses={courses} initialCourseId={retentionCourse} />}
        {loopActive === "error" && (
          <div role="status" style={{ margin: "14px 32px 0", fontSize: 13 }}>
            <p>Couldn&apos;t load due reviews. Your flashcards are still available.</p>
            <button type="button" className="btn btn--sm" onClick={retryLoopStatus} data-testid="review-status-retry">
              Retry due reviews
            </button>
          </div>
        )}
        <div style={{ padding: "14px 32px", display: "flex", alignItems: "center", gap: 8, borderBottom: "1px solid var(--border)", flexWrap: "wrap" }}>
          <FilterPills
            options={[
              { value: "all", label: "All topics" },
              ...topics.map((t) => ({ value: t, label: t })),
            ]}
            value={topicFilter}
            onChange={setTopicFilter}
            gap={8}
          />
          <div style={{ flex: 1 }} />
          {docsUsed !== null && (
            <span className="chip chip--accent" title="Library documents used as context for generation">
              Generated using {docsUsed} library doc{docsUsed === 1 ? "" : "s"}
            </span>
          )}
          <button
            className="btn btn--sm"
            onClick={() => setImportOpen(true)}
            disabled={!userId}
          >
            <Icon name="up" size={12} /> Import
          </button>
          <button
            className="btn btn--sm btn--primary"
            onClick={generate}
            disabled={generating || !userId}
          >
            <Icon name="sparkle" size={12} /> {generating ? "Generating…" : "Generate cards"}
          </button>
        </div>

        <div style={{ flex: 1, padding: "40px 32px", display: "flex", flexDirection: "column", alignItems: "center", gap: 22, overflowY: "auto" }}>
          {loading && <FlashcardsSkeleton />}
          {loadError && <div role="alert"><p>{loadError}</p><button type="button" className="btn btn--sm" data-testid="flashcards-retry" onClick={load}>Retry flashcards</button></div>}
          {filtered.length === 0 && !loading && !loadError && (
            <div style={{ textAlign: "center", color: "var(--text-muted)", padding: "40px 0" }}>
              <div className="h-serif" style={{ fontSize: 20 }}>No cards here yet</div>
              <div style={{ fontSize: 13, marginTop: 6 }}>
                {courseId === "all"
                  ? "Pick a course and generate cards from your library material."
                  : "Generate cards for this course to start reviewing."}
              </div>
            </div>
          )}

          {filtered.length > 0 && card && (
            <>
              <div style={{ width: "100%", maxWidth: 620 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--text-muted)", marginBottom: 8 }}>
                  <span>Card {idx + 1} of {filtered.length}</span>
                  <span className="mono">{card.topic || ""}</span>
                </div>
                <div style={{ height: 6, background: "var(--bg-soft)", borderRadius: "var(--r-full)", overflow: "hidden" }}>
                  <div style={{
                    width: "100%", height: "100%",
                    background: "var(--accent)",
                    transformOrigin: "left",
                    transform: `scaleX(${(idx + 1) / filtered.length})`,
                    transition: "transform var(--dur) var(--ease)",
                  }} />
                </div>
              </div>

              <FlipCard flipped={flipped} onFlip={() => setFlipped(f => !f)} front={card.front} back={card.back} />

              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center" }}>
                {ratingOptions.map(r => (
                  <button
                    key={r.n}
                    onClick={() => rate(r.n)}
                    disabled={!flipped}
                    title={`${r.label} (press ${r.hint})`}
                    style={{
                      padding: "10px 20px", borderRadius: "var(--r-sm)",
                      border: `1.5px solid ${r.color}`,
                      background: "transparent", color: r.color,
                      fontWeight: 600, fontSize: 13, textTransform: "capitalize",
                      display: "flex", alignItems: "center", gap: 8,
                      opacity: flipped ? 1 : 0.4, cursor: flipped ? "pointer" : "not-allowed",
                    }}
                  >
                    <span style={{ fontSize: 16 }}>{r.emoji}</span>
                    {r.label}
                    <span className="mono" style={{
                      fontSize: 10, padding: "1px 5px", borderRadius: "var(--r-xs)",
                      background: `${r.color}22`,
                    }}>{r.hint}</span>
                  </button>
                ))}
              </div>

              <button
                onClick={remove}
                className="btn btn--sm btn--ghost"
                style={{ color: "var(--err)", fontSize: 11 }}
                title="Delete this card"
              >
                <Icon name="x" size={11} /> Delete card
              </button>

              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                Space to flip · 1 / 2 / 3 to rate
              </div>
            </>
          )}
        </div>
      </div>
      {!isMobile && (
        <aside style={{
          width: 220, borderLeft: "1px solid var(--border)", background: "var(--bg-subtle)",
          padding: 16, overflowY: "auto", flexShrink: 0,
        }}>
          <div className="label-micro" style={{ marginBottom: 10 }}>Course</div>
          <CourseFilterRow
            label="All courses"
            active={courseId === "all"}
            onClick={() => { setCourseId("all"); setTopicFilter("all"); }}
          />
          {courses.map(c => (
            <CourseFilterRow
              key={c.course_id}
              label={c.course_code || c.course_name}
              subLabel={c.course_code ? c.course_name : undefined}
              color={c.color || undefined}
              active={courseId === c.course_id}
              onClick={() => { setCourseId(c.course_id); setTopicFilter("all"); }}
            />
          ))}
        </aside>
      )}
      <FlashcardImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        courses={courses}
        defaultCourseId={courseId !== "all" ? courseId : courses[0]?.course_id}
        defaultTopic={topicFilter !== "all" ? topicFilter : ""}
        documents={docs}
        onImported={() => { load(); }}
      />
    </div>
  );
}

function FlipCard({ flipped, onFlip, front, back }: { flipped: boolean; onFlip: () => void; front: string; back: string }) {
  return (
    <div
      onClick={onFlip}
      style={{
        width: "100%", maxWidth: 620, minHeight: 320,
        perspective: 1400, cursor: "pointer",
      }}
    >
      <div
        style={{
          position: "relative", width: "100%", minHeight: 320,
          transformStyle: "preserve-3d",
          transition: "transform 500ms cubic-bezier(.2,.85,.35,1)",
          transform: flipped ? "rotateY(180deg)" : "rotateY(0deg)",
        }}
      >
        <Face label="Question" text={front} />
        <Face label="Answer" text={back} back />
      </div>
    </div>
  );
}

function Face({ label, text, back = false }: { label: string; text: string; back?: boolean }) {
  return (
    <div
      style={{
        position: back ? "absolute" : "relative",
        inset: back ? 0 : undefined,
        width: "100%", minHeight: 320,
        background: "var(--bg-panel)", border: "1px solid var(--border)",
        borderRadius: "var(--r-xl)", padding: 36,
        boxShadow: "var(--shadow-md)",
        display: "flex", flexDirection: "column", justifyContent: "center",
        backfaceVisibility: "hidden",
        transform: back ? "rotateY(180deg)" : undefined,
      }}
    >
      <div className="label-micro" style={{ marginBottom: 14 }}>{label}</div>
      <div className="h-serif" style={{ fontSize: back ? 20 : 24, lineHeight: 1.35, fontWeight: 500 }}>
        <MarkdownChat>{text}</MarkdownChat>
      </div>
      {!back && (
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 18 }}>Click or press Space to reveal</div>
      )}
    </div>
  );
}

function CourseFilterRow({
  label, subLabel, color, active, onClick,
}: {
  label: string; subLabel?: string; color?: string; active: boolean; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%", display: "flex", alignItems: "center", gap: 8,
        padding: "8px 10px", borderRadius: "var(--r-sm)", marginBottom: 4,
        background: active ? "var(--bg-panel)" : "transparent",
        border: active ? "1px solid var(--border)" : "1px solid transparent",
        textAlign: "left",
      }}
    >
      <span style={{
        width: 8, height: 8, borderRadius: "50%",
        background: color || "var(--text-muted)",
      }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: active ? 600 : 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</div>
        {subLabel && <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{subLabel}</div>}
      </div>
    </button>
  );
}
