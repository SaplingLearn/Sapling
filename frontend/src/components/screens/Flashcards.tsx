"use client";
/**
 * Flashcards: spaced review with ratings and a 3D flip, on its own route.
 *
 * This was `/study?mode=cards` — a pane inside the pre-redesign Study screen's
 * tab strip. The Study hub (Sapling Study v3) sends students straight here
 * instead, so the pane owns the page: it loads the courses itself and scopes
 * them to the active term exactly as its old host did.
 *
 * Deep link from the hub: /flashcards?course=<id>&concepts=A|B
 */
import React from "react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

// Lazy-load to keep mermaid/katex/highlight.js out of the OpenNext server
// bundle. See ChatPanel.tsx for the rationale.
const MarkdownChat = dynamic(
  () => import("../chat/MarkdownChat").then((m) => m.MarkdownChat),
  { ssr: false, loading: () => null },
);
import { TopBar } from "../TopBar";
import { AIDisclaimerChip } from "../chat/AIDisclaimerChip";
import { Icon } from "../Icon";
import { FilterPills } from "@/components/ui";
import { FlashcardsSkeleton } from "../Skeleton";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { useActiveSemester, courseInTerm } from "@/lib/useActiveSemester";
import { humanizeError } from "@/lib/errorMessage";
import {
  getCourses,
  getDocuments,
  getFlashcards,
  generateFlashcards,
  rateFlashcard,
  deleteFlashcard,
  type EnrolledCourse,
} from "@/lib/api";
import { FlashcardImportModal } from "../flashcards/FlashcardImportModal";

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
export function Flashcards() {
  const isMobile = useIsMobile();
  const { userId, userReady } = useUser();
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [activeSemester, , semesterHydrated] = useActiveSemester();

  React.useEffect(() => {
    if (!userReady || !userId) return;
    getCourses(userId)
      .then(r => setCourses(r.courses || []))
      .catch(err => console.error("flashcards courses load failed", err));
  }, [userReady, userId]);

  // Same term scoping the old Study host applied before handing the pane its
  // course list.
  const scopedCourses = React.useMemo(
    () => (activeSemester ? courses.filter(c => courseInTerm(c, activeSemester)) : courses),
    [courses, activeSemester],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100%" }}>
      <TopBar
        title="Flashcards"
        subtitle="Spaced review with ratings and a 3D flip"
        actions={
          <>
            <Link href="/study" className="btn btn--sm btn--ghost" aria-label="Back to the Study hub">
              <Icon name="chevron-left" size={12} /> Study
            </Link>
            <AIDisclaimerChip />
          </>
        }
      />
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        <FlashcardsMode
          courses={scopedCourses}
          isMobile={isMobile}
          semester={activeSemester}
          semesterReady={semesterHydrated}
        />
      </div>
    </div>
  );
}

// ── the review pane ──────────────────────────────────────────────────────────

function FlashcardsMode({
  courses,
  isMobile,
  semester,
  semesterReady,
}: {
  courses: EnrolledCourse[];
  isMobile: boolean;
  // See GuideMode: "" = All semesters (unscoped); fetches gate on
  // semesterReady so a stored term never double-fetches (#141).
  semester: string;
  semesterReady: boolean;
}) {
  const toast = useToast();
  const { userId } = useUser();
  const [cards, setCards] = React.useState<RawCard[]>([]);
  const searchParams = useSearchParams();
  // Deep link from the Study hub: /study?mode=cards&course=…&concepts=A|B
  const [courseId, setCourseId] = React.useState<string>(searchParams.get("course") || "all");
  const [concepts, setConcepts] = React.useState<string[]>(
    (searchParams.get("concepts") || "").split("|").map(x => x.trim()).filter(Boolean),
  );
  const [topicFilter, setTopicFilter] = React.useState<string>("all");
  const [idx, setIdx] = React.useState(0);
  const [flipped, setFlipped] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [docsUsed, setDocsUsed] = React.useState<number | null>(null);
  const [importOpen, setImportOpen] = React.useState(false);
  const [docs, setDocs] = React.useState<{ id: string; file_name: string; category?: string }[]>([]);
  // Review-session state (#769). `rating` is the in-flight guard: one rating
  // per card, however many times the button/key fires while it's saving
  // (the ref closes the same-tick gap before the state re-renders). `done`
  // is the explicit end-of-deck state — rating the last card used to wrap
  // silently back to card 1.
  const [rating, setRating] = React.useState(false);
  const ratingRef = React.useRef(false);
  const [done, setDone] = React.useState(false);
  // Card id to re-anchor on after a reload that must keep the reviewer's
  // place (generate): indexes shift when cards are added, ids don't.
  const anchorRef = React.useRef<string | null>(null);
  const cardsReq = useLatestRequest();

  React.useEffect(() => {
    if (!userId) return;
    getDocuments(userId)
      .then(r => setDocs(r.documents || []))
      .catch(() => setDocs([]));
  }, [userId]);

  const load = React.useCallback(async (keepCardId?: string) => {
    if (!userId) return;
    // A term switch or a reload racing an older one: latest wins (#769).
    const run = cardsReq.begin();
    setLoading(true);
    try {
      const res = await getFlashcards(userId, undefined, semester || undefined);
      if (!run.isCurrent()) return;
      setCards(res.flashcards || []);
      if (keepCardId) {
        anchorRef.current = keepCardId;
      } else {
        setIdx(0);
        setFlipped(false);
        setDone(false);
      }
    } catch (err) {
      if (!run.isCurrent()) return;
      console.error("flashcards load failed", err);
    } finally {
      if (run.isCurrent()) setLoading(false);
    }
  }, [userId, semester, cardsReq]);

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
    if (concepts.length) {
      // Concepts picked on the hub: a card belongs when its topic names one.
      const wanted = concepts.map(c => c.toLowerCase());
      return out.filter(c => wanted.some(w => (c.topic || "").toLowerCase().includes(w)));
    }
    if (courseId !== "all") {
      const course = courses.find(c => c.course_id === courseId);
      const courseName = course?.course_name;
      if (courseName) out = out.filter(c => (c.topic || "").toLowerCase().includes(courseName.toLowerCase()));
    }
    if (topicFilter !== "all") out = out.filter(c => c.topic === topicFilter);
    return out;
  }, [cards, courseId, topicFilter, courses, concepts]);

  React.useEffect(() => {
    if (idx >= filtered.length) setIdx(0);
    setFlipped(false);
  }, [filtered.length, idx]);

  // Re-anchor after a keep-position reload (generate): declared after the
  // overflow reset above so its setIdx wins within the same commit.
  React.useEffect(() => {
    const id = anchorRef.current;
    if (!id) return;
    anchorRef.current = null;
    const at = filtered.findIndex(c => c.id === id);
    if (at >= 0) setIdx(at);
  }, [filtered]);

  // A different deck (course/topic filter) is a fresh review, not a finished one.
  React.useEffect(() => { setDone(false); }, [courseId, topicFilter, concepts]);

  const card = filtered[idx];

  const rate = React.useCallback(async (r: number) => {
    if (!card || ratingRef.current) return;
    ratingRef.current = true;
    setRating(true);
    try {
      await rateFlashcard(userId, card.id, r);
    } catch (err) {
      // On failure the card does NOT advance (#769): it stays up and
      // flipped, so pressing the rating again retries it. Advancing would
      // silently drop the review from the student's schedule.
      console.error("rate failed", err);
      toast.error(humanizeError(err, "Couldn't save that rating. Try again."));
      return;
    } finally {
      ratingRef.current = false;
      setRating(false);
    }
    setFlipped(false);
    if (idx >= filtered.length - 1) setDone(true);
    else setIdx(idx + 1);
  }, [card, userId, idx, filtered.length, toast]);

  const restart = () => {
    setDone(false);
    setIdx(0);
    setFlipped(false);
  };

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
      // A held key auto-repeats: one physical press = one action.
      if (e.repeat) return;
      if (e.code === "Space") { e.preventDefault(); setFlipped(f => !f); return; }
      if (!flipped || !card || done) return;
      if (e.key === "1") rate(1);
      else if (e.key === "2") rate(2);
      else if (e.key === "3") rate(3);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [flipped, rate, card, done]);

  const generate = async () => {
    if (!userId) return;
    const course = courses.find(c => c.course_id === courseId);
    const topic = concepts.length
      ? concepts.join(", ")
      : course ? course.course_name : (topicFilter !== "all" ? topicFilter : "");
    if (!topic) {
      toast.warn("Pick a course or topic before generating.");
      return;
    }
    setGenerating(true);
    setDocsUsed(null);
    try {
      // Term-scoped generation context: the selected term's course documents,
      // resolved by the selected course's id (#829) — the name is only the
      // prompt's label. A free-text topic sends no id.
      const r = await generateFlashcards(userId, topic, 5, semester || undefined, course?.course_id);
      setDocsUsed(r.context_used?.documents_found ?? 0);
      // Keep the reviewer's place (#769): mid-deck, stay on the current card;
      // past the end, continue at the first new card. Only an empty deck
      // starts over at card 1.
      const keepId: string | undefined = done ? r.flashcards[0]?.id : card?.id;
      if (done && keepId) setDone(false);
      await load(keepId);
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
        <div style={{ padding: "14px 32px", display: "flex", alignItems: "center", gap: 8, borderBottom: "1px solid var(--border)", flexWrap: "wrap" }}>
          <FilterPills
            options={[
              { value: "all", label: "All topics" },
              ...topics.map((t) => ({ value: t, label: t })),
            ]}
            value={topicFilter}
            onChange={v => { setTopicFilter(v); setConcepts([]); }}
            gap={8}
          />
          {concepts.length > 0 && (
            <button
              className="chip chip--accent"
              onClick={() => setConcepts([])}
              title="Show every card again"
            >
              {concepts.join(", ")} <Icon name="x" size={10} />
            </button>
          )}
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
            <Icon name="upload" size={12} /> Import
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
          {filtered.length === 0 && !loading && (
            <div style={{ textAlign: "center", color: "var(--text-muted)", padding: "40px 0" }}>
              <div className="h-serif" style={{ fontSize: 20 }}>No cards here yet</div>
              <div style={{ fontSize: 13, marginTop: 6 }}>
                {courseId === "all"
                  ? "Pick a course and generate cards from your library material."
                  : "Generate cards for this course to start reviewing."}
              </div>
            </div>
          )}

          {done && filtered.length > 0 && !loading && (
            <div style={{ textAlign: "center", padding: "40px 0" }}>
              <div className="h-serif" style={{ fontSize: 20 }}>Deck complete</div>
              <div style={{ fontSize: 13, marginTop: 6, color: "var(--text-muted)" }}>
                You reviewed all {filtered.length} card{filtered.length === 1 ? "" : "s"}.
              </div>
              <button className="btn btn--sm btn--primary" style={{ marginTop: 16 }} onClick={restart}>
                Review again
              </button>
            </div>
          )}

          {filtered.length > 0 && card && !done && (
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
                    disabled={!flipped || rating}
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
            onClick={() => { setCourseId("all"); setTopicFilter("all"); setConcepts([]); }}
          />
          {courses.map(c => (
            <CourseFilterRow
              key={c.course_id}
              label={c.course_code || c.course_name}
              subLabel={c.course_code ? c.course_name : undefined}
              color={c.color || undefined}
              active={courseId === c.course_id}
              onClick={() => { setCourseId(c.course_id); setTopicFilter("all"); setConcepts([]); }}
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
