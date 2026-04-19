"use client";
import React from "react";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { Pill } from "../Pill";
import { CustomSelect } from "../CustomSelect";
import { MarkdownChat } from "../MarkdownChat";
import { useToast } from "../ToastProvider";
import { useIsMobile } from "@/lib/useIsMobile";
import { useUser } from "@/context/UserContext";
import {
  getCourses,
  getStudyGuideExams,
  getStudyGuide,
  regenerateStudyGuide,
  getCachedStudyGuides,
  getFlashcards,
  generateFlashcards,
  rateFlashcard,
  type EnrolledCourse,
  type StudyGuideContent,
  type StudyGuideExam,
  type StudyGuideCacheEntry,
} from "@/lib/api";

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
  { n: 3, label: "good", color: "var(--accent)", emoji: "✨", hint: "3" },
];

export function Study() {
  const isMobile = useIsMobile();
  const { userId, userReady } = useUser();
  const [mode, setMode] = React.useState<Mode>("guide");
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);

  React.useEffect(() => {
    if (!userReady || !userId) return;
    getCourses(userId)
      .then(r => setCourses(r.courses || []))
      .catch(err => console.error("study courses load failed", err));
  }, [userReady, userId]);

  const actions = (
    <div style={{ display: "flex", border: "1px solid var(--border)", borderRadius: "var(--r-sm)", overflow: "hidden" }}>
      {([["guide", "Study Guide"], ["cards", "Flashcards"]] as const).map(([v, label]) => (
        <button
          key={v}
          onClick={() => setMode(v)}
          style={{
            padding: "6px 14px", fontSize: 12, fontWeight: 600,
            background: mode === v ? "var(--accent-soft)" : "transparent",
            color: mode === v ? "var(--accent)" : "var(--text-dim)",
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
      <TopBar
        breadcrumb="Home / Study"
        title="Study"
        subtitle={mode === "guide" ? "Exam-ready guides from your course material" : "Spaced review with ratings and a 3D flip"}
        actions={actions}
      />
      {mode === "guide" ? (
        <GuideMode courses={courses} isMobile={isMobile} />
      ) : (
        <FlashcardsMode courses={courses} isMobile={isMobile} />
      )}
    </div>
  );
}

// ── Study Guide mode ─────────────────────────────────────────────────────────

function GuideMode({ courses, isMobile }: { courses: EnrolledCourse[]; isMobile: boolean }) {
  const toast = useToast();
  const { userId } = useUser();
  const [courseId, setCourseId] = React.useState<string>("");
  const [examId, setExamId] = React.useState<string>("");
  const [exams, setExams] = React.useState<StudyGuideExam[]>([]);
  const [guide, setGuide] = React.useState<StudyGuideContent | null>(null);
  const [generatedAt, setGeneratedAt] = React.useState<string>("");
  const [cached, setCached] = React.useState<boolean>(false);
  const [loadingExams, setLoadingExams] = React.useState(false);
  const [loadingGuide, setLoadingGuide] = React.useState(false);
  const [regenerating, setRegenerating] = React.useState(false);
  const [recent, setRecent] = React.useState<StudyGuideCacheEntry[]>([]);

  const loadRecent = React.useCallback(async () => {
    if (!userId) return;
    try {
      const r = await getCachedStudyGuides(userId);
      setRecent(r.guides || []);
    } catch (err) {
      console.error("recent guides failed", err);
    }
  }, [userId]);

  React.useEffect(() => { loadRecent(); }, [loadRecent]);

  React.useEffect(() => {
    setExamId("");
    setExams([]);
    setGuide(null);
    if (!courseId || !userId) return;
    setLoadingExams(true);
    getStudyGuideExams(userId, courseId)
      .then(r => setExams(r.exams || []))
      .catch(err => toast.error(`Couldn't load exams: ${String(err)}`))
      .finally(() => setLoadingExams(false));
  }, [courseId, userId, toast]);

  const loadGuide = React.useCallback(async (cid: string, eid: string) => {
    if (!userId) return;
    setLoadingGuide(true);
    try {
      const r = await getStudyGuide(userId, cid, eid);
      setGuide(r.guide);
      setGeneratedAt(r.generated_at);
      setCached(r.cached);
      if (!r.cached) loadRecent();
    } catch (err) {
      toast.error(`Couldn't load guide: ${String(err)}`);
    } finally {
      setLoadingGuide(false);
    }
  }, [userId, toast, loadRecent]);

  React.useEffect(() => {
    if (courseId && examId) loadGuide(courseId, examId);
  }, [courseId, examId, loadGuide]);

  const openRecent = (entry: StudyGuideCacheEntry) => {
    setCourseId(entry.course_id);
    setExamId(entry.exam_id);
  };

  const regenerate = async () => {
    if (!userId || !courseId || !examId) return;
    setRegenerating(true);
    try {
      const r = await regenerateStudyGuide(userId, courseId, examId);
      setGuide(r.guide);
      setGeneratedAt(r.generated_at);
      setCached(false);
      await loadRecent();
      toast.success("Study guide regenerated.");
    } catch (err) {
      toast.error(`Regenerate failed: ${String(err)}`);
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      {!isMobile && (
        <aside style={{
          width: 260, borderRight: "1px solid var(--border)", background: "var(--bg-subtle)",
          padding: 16, overflowY: "auto", flexShrink: 0,
        }}>
          <div className="label-micro" style={{ marginBottom: 10 }}>Recent guides</div>
          {recent.length === 0 && (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No generated guides yet.</div>
          )}
          {recent.slice(0, 20).map(r => (
            <button
              key={r.id}
              onClick={() => openRecent(r)}
              style={{
                width: "100%", textAlign: "left", padding: "10px 12px",
                borderRadius: "var(--r-sm)", marginBottom: 6,
                background: r.course_id === courseId && r.exam_id === examId ? "var(--bg-panel)" : "transparent",
                border: r.course_id === courseId && r.exam_id === examId ? "1px solid var(--border)" : "1px solid transparent",
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.exam_title || "Untitled exam"}
              </div>
              <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
                {r.course_name} · {new Date(r.generated_at).toLocaleDateString()}
              </div>
            </button>
          ))}
        </aside>
      )}

      <div style={{ flex: 1, overflowY: "auto", padding: "24px 32px" }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 20 }}>
          <div style={{ minWidth: 220 }}>
            <div className="label-micro" style={{ marginBottom: 4 }}>Course</div>
            <CustomSelect
              value={courseId}
              onChange={v => setCourseId(v)}
              placeholder="Pick a course…"
              options={courses.map(c => ({
                value: c.course_id,
                label: c.course_code || c.course_name,
                description: c.course_code ? c.course_name : undefined,
              }))}
            />
          </div>
          <div style={{ minWidth: 260 }}>
            <div className="label-micro" style={{ marginBottom: 4 }}>Exam</div>
            <CustomSelect
              value={examId}
              onChange={v => setExamId(v)}
              placeholder={loadingExams ? "Loading…" : (courseId ? "Pick an exam…" : "Select a course first")}
              disabled={!courseId || loadingExams}
              options={exams.map(e => ({
                value: e.id,
                label: e.title,
                description: e.due_date ? `Due ${e.due_date}` : undefined,
              }))}
            />
          </div>
          {guide && (
            <div style={{ marginLeft: "auto", alignSelf: "flex-end" }}>
              <button
                className="btn btn--sm"
                onClick={regenerate}
                disabled={regenerating || loadingGuide}
              >
                <Icon name="sparkle" size={12} /> {regenerating ? "Regenerating…" : "Regenerate"}
              </button>
            </div>
          )}
        </div>

        {!courseId && (
          <EmptyHint
            title="Pick a course to get started"
            body="Your generated study guides live here — grouped by exam and built from the documents in your library."
          />
        )}
        {courseId && !examId && !loadingExams && exams.length === 0 && (
          <EmptyHint
            title="No exams found for this course"
            body="Import a syllabus on the Calendar page, or add an assignment with type = Exam."
          />
        )}
        {courseId && !examId && exams.length > 0 && (
          <EmptyHint title="Choose an exam" body="The guide will be generated from your course material the first time." />
        )}

        {(loadingGuide || regenerating) && (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
            Building your guide…
          </div>
        )}

        {!loadingGuide && guide && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div className="card" style={{ padding: "var(--pad-lg)" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <div className="h-serif" style={{ fontSize: 22, fontWeight: 500 }}>{guide.exam}</div>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  {guide.due_date && <span className="chip">Due {guide.due_date}</span>}
                  <span className="chip" style={{ opacity: 0.7 }}>
                    {cached ? "Cached" : "Fresh"} · {generatedAt ? new Date(generatedAt).toLocaleString() : ""}
                  </span>
                </div>
              </div>
              {guide.overview && (
                <div style={{ marginTop: 10, fontSize: 13, color: "var(--text-dim)", lineHeight: 1.55 }}>
                  <MarkdownChat>{guide.overview}</MarkdownChat>
                </div>
              )}
            </div>

            {(guide.topics || []).map((t, i) => (
              <div key={`${t.name}-${i}`} className="card" style={{ padding: "var(--pad-lg)" }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                  <span className="label-micro">Topic {i + 1}</span>
                  <div className="h-serif" style={{ fontSize: 18, fontWeight: 500 }}>{t.name}</div>
                </div>
                {t.importance && (
                  <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-muted)", fontStyle: "italic" }}>
                    <MarkdownChat>{t.importance}</MarkdownChat>
                  </div>
                )}
                {(t.concepts || []).length > 0 && (
                  <ul style={{ margin: "10px 0 0 18px", padding: 0 }}>
                    {(t.concepts || []).map((c, j) => (
                      <li key={j} style={{ fontSize: 13, color: "var(--text)", marginBottom: 4, lineHeight: 1.5 }}>
                        <MarkdownChat>{c}</MarkdownChat>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Flashcards mode ──────────────────────────────────────────────────────────

function FlashcardsMode({ courses, isMobile }: { courses: EnrolledCourse[]; isMobile: boolean }) {
  const toast = useToast();
  const { userId } = useUser();
  const [cards, setCards] = React.useState<RawCard[]>([]);
  const [courseId, setCourseId] = React.useState<string>("all");
  const [topicFilter, setTopicFilter] = React.useState<string>("all");
  const [idx, setIdx] = React.useState(0);
  const [flipped, setFlipped] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [docsUsed, setDocsUsed] = React.useState<number | null>(null);

  const load = React.useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const res = await getFlashcards(userId);
      setCards(res.flashcards || []);
      setIdx(0);
      setFlipped(false);
    } catch (err) {
      console.error("flashcards load failed", err);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  React.useEffect(() => { load(); }, [load]);

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
      const r = await generateFlashcards(userId, topic, 5);
      setDocsUsed(r.context_used?.documents_found ?? 0);
      await load();
      toast.success(`Added ${r.flashcards.length} new card${r.flashcards.length === 1 ? "" : "s"}.`);
    } catch (err) {
      toast.error(`Generate failed: ${String(err)}`);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      {!isMobile && (
        <aside style={{
          width: 220, borderRight: "1px solid var(--border)", background: "var(--bg-subtle)",
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

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <div style={{ padding: "14px 32px", display: "flex", alignItems: "center", gap: 8, borderBottom: "1px solid var(--border)", flexWrap: "wrap" }}>
          <Pill active={topicFilter === "all"} onClick={() => setTopicFilter("all")}>All topics</Pill>
          {topics.map(t => (
            <Pill key={t} active={topicFilter === t} onClick={() => setTopicFilter(t)}>{t}</Pill>
          ))}
          <div style={{ flex: 1 }} />
          {docsUsed !== null && (
            <span className="chip chip--accent" title="Library documents used as context for generation">
              Generated using {docsUsed} library doc{docsUsed === 1 ? "" : "s"}
            </span>
          )}
          <button
            className="btn btn--sm btn--primary"
            onClick={generate}
            disabled={generating || !userId}
          >
            <Icon name="sparkle" size={12} /> {generating ? "Generating…" : "Generate cards"}
          </button>
        </div>

        <div style={{ flex: 1, padding: "40px 32px", display: "flex", flexDirection: "column", alignItems: "center", gap: 22, overflowY: "auto" }}>
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

          {filtered.length > 0 && card && (
            <>
              <div style={{ width: "100%", maxWidth: 620 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--text-muted)", marginBottom: 8 }}>
                  <span>Card {idx + 1} of {filtered.length}</span>
                  <span className="mono">{card.topic || ""}</span>
                </div>
                <div style={{ height: 6, background: "var(--bg-soft)", borderRadius: "var(--r-full)", overflow: "hidden" }}>
                  <div style={{
                    width: `${((idx + 1) / filtered.length) * 100}%`,
                    height: "100%", background: "var(--accent)", transition: "width var(--dur) var(--ease)",
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
                      padding: "10px 20px", borderRadius: "var(--r-md)",
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

              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                Space to flip · 1 / 2 / 3 to rate
              </div>
            </>
          )}
        </div>
      </div>
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

function EmptyHint({ title, body }: { title: string; body: string }) {
  return (
    <div className="card" style={{ padding: "32px 28px", textAlign: "center", color: "var(--text-muted)" }}>
      <div className="h-serif" style={{ fontSize: 18, color: "var(--text)", marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 13 }}>{body}</div>
    </div>
  );
}
