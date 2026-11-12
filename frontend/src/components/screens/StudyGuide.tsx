"use client";
/**
 * Study Guide: an exam-ready guide built from a course's materials, with the
 * guides already generated listed beside it.
 *
 * This is the guide pane of the pre-v3 Study screen, as a page of its own at
 * /study/guide (Flashcards and Quiz were split out the same way). The Study
 * hub's Study Guide buttons open it on the course and exam the hub is showing;
 * it is not in the nav, so it carries a back button to the hub.
 */
import React from "react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { TopBar } from "../TopBar";
import { BackLink } from "../BackLink";
import { AIDisclaimerChip } from "../chat/AIDisclaimerChip";
import { Icon } from "../Icon";
import { CustomSelect } from "../CustomSelect";

// Lazy-load to keep mermaid/katex/highlight.js out of the OpenNext
// server bundle. See ChatPanel.tsx for the rationale.
const MarkdownChat = dynamic(
  () => import("../chat/MarkdownChat").then((m) => m.MarkdownChat),
  { ssr: false, loading: () => null },
);
import { StudyGuideSkeleton } from "../Skeleton";
import { useToast } from "../ToastProvider";
import { useIsMobile } from "@/lib/useIsMobile";
import { humanizeError, isNotFound } from "@/lib/errorMessage";
import { useUser } from "@/context/UserContext";
import { useActiveSemester, courseInTerm } from "@/lib/useActiveSemester";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { courseSelectOptions } from "@/lib/courseSelectOptions";
import { studyHref } from "@/lib/toolHrefs";
import { useIsNavHidden } from "@/lib/useNavHidden";
import {
  getCourses,
  getStudyGuideExams,
  getStudyGuide,
  regenerateStudyGuide,
  getCachedStudyGuides,
  type EnrolledCourse,
  type StudyGuideContent,
  type StudyGuideExam,
  type StudyGuideCacheEntry,
} from "@/lib/api";
import {
  examGoneBody,
  examPickerPlaceholder,
  guideLoadProblem,
  isOpenGuide,
  loadTerm,
  noExamsBody,
  stepNumberColor,
  type GuideProblem,
} from "./studyGuideView";

export function StudyGuide() {
  const isMobile = useIsMobile();
  const { userId, userReady } = useUser();
  const searchParams = useSearchParams();
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [activeSemester, , semesterHydrated] = useActiveSemester();
  // Read once: these seed the pickers, they do not drive them.
  const [opened] = React.useState(() => ({
    course: searchParams.get("course"),
    exam: searchParams.get("exam"),
  }));

  React.useEffect(() => {
    if (!userReady || !userId) return;
    getCourses(userId)
      .then(r => setCourses(r.courses || []))
      .catch(err => console.error("study guide courses load failed", err));
  }, [userReady, userId]);

  // Scope the course picker to the active semester's courses, as the hub does.
  const scopedCourses = React.useMemo(
    () => (activeSemester ? courses.filter(c => courseInTerm(c, activeSemester)) : courses),
    [courses, activeSemester],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100%" }}>
      <TopBar
        title="Study Guide"
        subtitle="Exam-ready guides built from your course materials"
        actions={<><AIDisclaimerChip /><BackLink href={studyHref(opened.course)} label="Study" /></>}
      />
      <div className="tool-enter" style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <GuideMode
          courses={scopedCourses}
          isMobile={isMobile}
          semester={activeSemester}
          semesterReady={semesterHydrated}
          initialCourseId={opened.course}
          initialExamId={opened.exam}
        />
      </div>
    </div>
  );
}

// ── The guide ────────────────────────────────────────────────────────────────
function GuideMode({
  courses,
  isMobile,
  semester,
  semesterReady,
  initialCourseId,
  initialExamId,
}: {
  courses: EnrolledCourse[];
  isMobile: boolean;
  /** The course (and exam) the page was opened on: the Study hub's Study Guide
   *  button passes the ones it is showing, so the guide opens there instead of
   *  on two empty pickers. */
  initialCourseId?: string | null;
  initialExamId?: string | null;
  // The active semester ("" = All semesters → unscoped fetches, #141) and its
  // hydration flag — fetches wait for it so a stored term never produces an
  // unscoped-then-scoped double fetch (the Dashboard pattern).
  semester: string;
  semesterReady: boolean;
}) {
  const toast = useToast();
  const { userId } = useUser();
  const [courseId, setCourseId] = React.useState<string>(initialCourseId || "");
  // The exam asked for in the URL, applied once the course's exam list is in
  // and only if it is ON that list: the hub's tabs also hold quizzes, which
  // have no study guide, and asking for one would 404 into "exam not found".
  const wantedExamRef = React.useRef<string | null>(initialExamId || null);
  // That exam once applied, until its one load has run. The exam list spans
  // every term the student took the course in, but a guide resolves against
  // one offering, so an exam from another term 404s. When the student picked
  // it, the "exam isn't around" card is the answer; when the URL picked it,
  // that card blames them for a choice they never made, so the page falls
  // back to the pickers instead.
  const urlExamRef = React.useRef<string | null>(null);
  const [examId, setExamId] = React.useState<string>("");
  const [exams, setExams] = React.useState<StudyGuideExam[]>([]);
  const [guide, setGuide] = React.useState<StudyGuideContent | null>(null);
  const [generatedAt, setGeneratedAt] = React.useState<string>("");
  const [cached, setCached] = React.useState<boolean>(false);
  const [loadingExams, setLoadingExams] = React.useState(false);
  const [loadingGuide, setLoadingGuide] = React.useState(false);
  const [regenerating, setRegenerating] = React.useState(false);
  const [recent, setRecent] = React.useState<StudyGuideCacheEntry[]>([]);
  const [guideProblem, setGuideProblem] = React.useState<GuideProblem | null>(null);
  // "" = resolved unscoped. See loadGuide.
  const [loadedTerm, setLoadedTerm] = React.useState<string>("");
  // Latest-request-wins slots (#769): one for the exam list, one shared by
  // loadGuide + regenerate (both write the displayed guide, so whichever was
  // started last owns it).
  const examsReq = useLatestRequest();
  const guideReq = useLatestRequest();

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

  // Dropping the exam selection is a response to two EVENTS — the user picking
  // a different course, and the active term changing — never to `courseId`
  // simply differing from its last value. That distinction is the whole of
  // #476: openRecent changes courseId too, and a courseId-keyed effect can't
  // tell a deliberate open from a user switch, so it wiped the exam openRecent
  // had just set. It also landed a render late, so the loader below still got
  // one read out of the stale pair before the reset applied.
  const clearSelection = () => {
    setExamId("");
    setGuide(null);
    setGuideProblem(null);
  };

  // Guarded on an actual CHANGE. CustomSelect fires onChange for the
  // already-selected option too, and the effect this reset came out of got that
  // for free — setCourseId(same) bails out, so the effect never re-ran. On a
  // plain handler it has to be explicit, or re-confirming the course you are
  // already on wipes the guide you are reading.
  const selectCourse = (next: string) => {
    if (next === courseId) return;
    wantedExamRef.current = null;
    setCourseId(next);
    clearSelection();
  };

  // A term switch re-scopes the exam list, so an exam picked under the old term
  // need not exist in the new one. Adjusted during render (the StudyModePanel
  // pattern above) rather than in an effect: an effect-time reset commits once
  // on the stale pair first, re-reading the old exam under the new term and
  // landing on the strict resolver. `null` = uninitialized, so hydration
  // ("" → the stored term) is not a switch.
  const [scopedTerm, setScopedTerm] = React.useState<string | null>(null);
  if (semesterReady && scopedTerm !== semester) {
    if (scopedTerm !== null) clearSelection();
    setScopedTerm(semester);
  }

  // The OPTIONS follow the active selector, deliberately: #475 pins only the
  // recent-open's own load to the entry's term, and later picker-driven loads
  // go back to the selector — so listing the entry's term here would offer
  // exams that the next load would then 404 on.
  // Known edge that leaves: open a rail entry whose term ISN'T the active one
  // and its exam is absent from this list, so CustomSelect falls back to the
  // placeholder while the guide and Regenerate are live and correctly aimed at
  // `loadedTerm`. Squaring that needs the screen to track "the term I'm
  // viewing" as one thing across list + loads — a #475 change, not this one.
  React.useEffect(() => {
    setExams([]);
    if (!courseId || !userId || !semesterReady) {
      setLoadingExams(false);
      return;
    }
    // A course/term switch mid-flight drops the old list's reply (#769), so a
    // slow course-A response can't land in course B's picker.
    const run = examsReq.begin();
    setLoadingExams(true);
    getStudyGuideExams(userId, courseId, semester || undefined)
      .then(r => {
        if (!run.isCurrent()) return;
        const list = r.exams || [];
        setExams(list);
        const wanted = wantedExamRef.current;
        wantedExamRef.current = null;
        if (wanted && list.some(e => e.id === wanted)) {
          urlExamRef.current = wanted;
          setExamId(wanted);
        }
      })
      .catch(err => {
        if (!run.isCurrent()) return;
        console.error("study exams load failed", err);
        toast.error(humanizeError(err, "Couldn't load the exams for this course."));
      })
      .finally(() => { if (run.isCurrent()) setLoadingExams(false); });
    return examsReq.cancel;
  }, [courseId, userId, toast, semester, semesterReady, examsReq]);

  // A pending recent-open's OWN term (#475 F1), consumed by exactly one load:
  // null = no pending recent open; "" = the entry has no term label, open
  // explicitly unscoped.
  const recentTermRef = React.useRef<string | null>(null);

  const loadGuide = React.useCallback(async (cid: string, eid: string, termOverride?: string) => {
    if (!userId) return;
    // termOverride pins the term for THIS load ("" = explicitly unscoped):
    // recent entries open as their own term (#475 F1) and retries replay the
    // term that failed. Without it, the active selector applies.
    const term = loadTerm(termOverride, semester);
    // Switching exams quickly must show the LAST pick's guide (#769): every
    // write below is gated on this run still being the latest.
    const run = guideReq.begin();
    const pickedByUrl = urlExamRef.current === eid;
    urlExamRef.current = null;
    setLoadingGuide(true);
    setGuideProblem(null);
    try {
      const r = await getStudyGuide(userId, cid, eid, term);
      if (!run.isCurrent()) return;
      setGuide(r.guide);
      // The term this guide was actually resolved under — which is the entry's
      // own term on a recent-open, not the active selector's (#475 F1).
      // Regenerate has to replay it, or it rebuilds against a different
      // offering than the one on screen.
      setLoadedTerm(term ?? "");
      setGeneratedAt(r.generated_at);
      setCached(r.cached);
      if (!r.cached) loadRecent();
    } catch (err) {
      if (!run.isCurrent()) return;
      setGuide(null);
      if (pickedByUrl && isNotFound(err)) {
        // See urlExamRef: keep the course, drop the exam, say nothing.
        setExamId("");
        return;
      }
      console.error("study guide load failed", err);
      // Missing (a card) or failed (a card with a retry, and a red toast):
      // see GuideProblem.
      const problem = guideLoadProblem(err, { courseId: cid, examId: eid, semester: term ?? "" });
      setGuideProblem(problem);
      if (problem.kind === "failed") toast.error(problem.message);
    } finally {
      // Only the latest run owns the spinner — an older run finishing must
      // not clear it while a newer one is still in flight.
      if (run.isCurrent()) setLoadingGuide(false);
    }
  }, [userId, toast, loadRecent, semester, guideReq]);

  React.useEffect(() => {
    if (courseId && examId) {
      // Consume a pending recent-open term so ONLY this load is pinned to the
      // entry's own term; later picker-driven loads follow the selector.
      const recentTerm = recentTermRef.current;
      recentTermRef.current = null;
      loadGuide(courseId, examId, recentTerm ?? undefined);
    } else {
      // Selection cleared (course/term switch): an in-flight load or
      // regenerate for the old exam must not land on the empty selection.
      guideReq.cancel();
      setLoadingGuide(false);
    }
  }, [courseId, examId, loadGuide, guideReq]);

  const openRecent = (entry: StudyGuideCacheEntry) => {
    // A deliberate open outranks the exam the URL asked for: if that one is
    // still waiting on the exam list, it must not replace this when the list
    // lands.
    wantedExamRef.current = null;
    // Already the selection: nothing changes, so no load will run to consume
    // the term below. Left armed, it would pin the NEXT picker-driven load to
    // this entry's term instead of the selector's.
    if (isOpenGuide(entry, courseId, examId)) return;
    // #475 F1: the entry's guide row keys on ITS offering/term, which need
    // not match the active selector — a Spring guide in the rail must open as
    // Spring, or the strict resolver cache-misses under the active term and
    // silently generates (and persists) a mismatched row.
    recentTermRef.current = entry.semester ?? "";
    setCourseId(entry.course_id);
    setExamId(entry.exam_id);
  };

  const regenerate = async () => {
    // Regeneration is meaningless without a target exam, and the endpoint
    // 400s on a blank one — bail before the request.
    if (!userId || !courseId || !examId) return;
    const run = guideReq.begin();
    setRegenerating(true);
    setGuideProblem(null);
    try {
      // Regenerates the term the DISPLAYED guide was read under, so rebuild
      // and read key on the same offering. Before #476 this could use the
      // active selector safely only because the button was unreachable on the
      // recent-open path — the one path where the two differ.
      const r = await regenerateStudyGuide(userId, courseId, examId, loadedTerm || undefined);
      // Picked another exam meanwhile: the rebuilt guide belongs to the old
      // one (persisted server-side either way), so don't paint it here.
      if (!run.isCurrent()) return;
      setGuide(r.guide);
      setGeneratedAt(r.generated_at);
      setCached(false);
      await loadRecent();
      toast.success("Study guide regenerated.");
    } catch (err) {
      if (!run.isCurrent()) return;
      console.error("study guide regenerate failed", err);
      toast.error(humanizeError(err, "Couldn't regenerate that study guide."));
    } finally {
      // Unconditional: at most one regenerate runs (the button is disabled
      // while it does), and a superseding guide load never owns this flag.
      setRegenerating(false);
    }
  };

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      <div style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "24px 32px" }}>
        <GuidePickers
          courses={courses}
          courseId={courseId}
          examId={examId}
          exams={exams}
          loadingExams={loadingExams}
          onSelectCourse={selectCourse}
          onSelectExam={setExamId}
          hasGuide={Boolean(guide)}
          regenerating={regenerating}
          loadingGuide={loadingGuide}
          onRegenerate={regenerate}
        />
        <GuideSelectionHint
          courseId={courseId}
          examId={examId}
          hasProblem={Boolean(guideProblem)}
          loadingExams={loadingExams}
          examCount={exams.length}
        />
        <GuideProblemHint
          problem={guideProblem}
          loadingGuide={loadingGuide}
          regenerating={regenerating}
          onRetry={loadGuide}
        />

        {(loadingGuide || regenerating) && <StudyGuideSkeleton />}

        {!loadingGuide && guide && (
          <GuideContent guide={guide} cached={cached} generatedAt={generatedAt} />
        )}
      </div>
      {!isMobile && (
        <RecentGuidesRail recent={recent} courseId={courseId} examId={examId} onOpen={openRecent} />
      )}
    </div>
  );
}

// The course + exam pickers, and Regenerate once a guide is on screen.
function GuidePickers({
  courses,
  courseId,
  examId,
  exams,
  loadingExams,
  onSelectCourse,
  onSelectExam,
  hasGuide,
  regenerating,
  loadingGuide,
  onRegenerate,
}: {
  courses: EnrolledCourse[];
  courseId: string;
  examId: string;
  exams: StudyGuideExam[];
  loadingExams: boolean;
  onSelectCourse: (next: string) => void;
  onSelectExam: (next: string) => void;
  hasGuide: boolean;
  regenerating: boolean;
  loadingGuide: boolean;
  onRegenerate: () => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 16,
        flexWrap: "wrap",
        alignItems: "flex-end",
        marginBottom: 20,
      }}
    >
      <div style={{ flex: "1 1 240px", minWidth: 220 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <span
            className="mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.08em",
              color: stepNumberColor(courseId, ""),
              transition: "color var(--dur) var(--ease)",
            }}
          >
            01
          </span>
          <span className="label-micro">Course</span>
        </div>
        <CustomSelect
          value={courseId}
          onChange={onSelectCourse}
          placeholder="Pick a course…"
          options={courseSelectOptions(courses)}
        />
      </div>
      <div style={{ flex: "1 1 240px", minWidth: 220 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <span
            className="mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.08em",
              color: stepNumberColor(examId, courseId),
              transition: "color var(--dur) var(--ease)",
            }}
          >
            02
          </span>
          <span className="label-micro">Exam</span>
        </div>
        <CustomSelect
          value={examId}
          onChange={v => onSelectExam(v)}
          placeholder={examPickerPlaceholder(loadingExams, courseId)}
          disabled={!courseId || loadingExams}
          options={exams.map(e => ({
            value: e.id,
            label: e.title,
            description: e.due_date ? `Due ${e.due_date}` : undefined,
          }))}
        />
      </div>
      {hasGuide && (
        <button
          className="btn btn--sm"
          onClick={onRegenerate}
          disabled={regenerating || loadingGuide || !examId}
        >
          <Icon name="sparkle" size={12} /> {regenerating ? "Regenerating…" : "Regenerate"}
        </button>
      )}
    </div>
  );
}

// What to do next when no exam is selected yet (no course / no exams / pick one).
function GuideSelectionHint({
  courseId,
  examId,
  hasProblem,
  loadingExams,
  examCount,
}: {
  courseId: string;
  examId: string;
  hasProblem: boolean;
  loadingExams: boolean;
  examCount: number;
}) {
  const calendarHidden = useIsNavHidden()("/calendar");
  return (
    <>
      {!courseId && (
        <EmptyHint
          title="Pick a course to get started"
          body="Your generated study guides live here — grouped by exam and built from the documents in your library."
        />
      )}
      {courseId && !examId && !hasProblem && !loadingExams && examCount === 0 && (
        <EmptyHint title="No exams for this course yet" body={noExamsBody(calendarHidden)} />
      )}
      {courseId && !examId && !hasProblem && examCount > 0 && (
        <EmptyHint title="Choose an exam" body="The guide will be generated from your course material the first time." />
      )}
    </>
  );
}

// A guide load that didn't produce a guide (see GuideProblem); hidden while a
// load or regenerate is in flight.
function GuideProblemHint({
  problem,
  loadingGuide,
  regenerating,
  onRetry,
}: {
  problem: GuideProblem | null;
  loadingGuide: boolean;
  regenerating: boolean;
  onRetry: (cid: string, eid: string, termOverride?: string) => void;
}) {
  const calendarHidden = useIsNavHidden()("/calendar");
  if (loadingGuide || regenerating || !problem) return null;
  if (problem.kind === "missing") {
    return problem.message ? (
      // #475 F4: the server said something more specific than "exam
      // deleted" (e.g. no offering in the requested term) — show it.
      <EmptyHint title="That guide isn't available" body={problem.message} />
    ) : (
      <EmptyHint title="That exam isn't around anymore" body={examGoneBody(calendarHidden)} />
    );
  }
  return (
    <EmptyHint
      title="That guide didn't come through"
      body={problem.message}
      action={
        <button
          className="btn btn--sm btn--primary"
          // Replays the exact load that failed — ids AND term (#475 F1).
          onClick={() =>
            onRetry(problem.courseId, problem.examId, problem.semester)
          }
          disabled={loadingGuide}
        >
          Try again
        </button>
      }
    />
  );
}

// The rendered guide: header card (title, due date, cache stamp, overview)
// followed by one card per topic.
function GuideContent({
  guide,
  cached,
  generatedAt,
}: {
  guide: StudyGuideContent;
  cached: boolean;
  generatedAt: string;
}) {
  return (
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
  );
}

// The desktop "Recent guides" side rail; the open guide's entry is highlighted.
function RecentGuidesRail({
  recent,
  courseId,
  examId,
  onOpen,
}: {
  recent: StudyGuideCacheEntry[];
  courseId: string;
  examId: string;
  onOpen: (entry: StudyGuideCacheEntry) => void;
}) {
  return (
    <aside style={{
      width: 260, borderLeft: "1px solid var(--border)", background: "var(--bg-subtle)",
      padding: 16, overflowY: "auto", flexShrink: 0,
    }}>
      <div className="label-micro" style={{ marginBottom: 10 }}>Recent guides</div>
      {recent.length === 0 && (
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No generated guides yet.</div>
      )}
      {recent.slice(0, 20).map(r => (
        <button
          key={r.id}
          onClick={() => onOpen(r)}
          style={{
            width: "100%", textAlign: "left", padding: "10px 12px",
            borderRadius: "var(--r-sm)", marginBottom: 6,
            background: isOpenGuide(r, courseId, examId) ? "var(--bg-panel)" : "transparent",
            border: isOpenGuide(r, courseId, examId) ? "1px solid var(--border)" : "1px solid transparent",
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
  );
}

function EmptyHint({ title, body, action }: { title: string; body: string; action?: React.ReactNode }) {
  return (
    <div className="card" style={{ padding: "32px 28px", textAlign: "center", color: "var(--text-muted)" }}>
      <div className="h-serif" style={{ fontSize: 18, color: "var(--text)", marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 13 }}>{body}</div>
      {action && (
        <div style={{ marginTop: 16, display: "flex", justifyContent: "center" }}>{action}</div>
      )}
    </div>
  );
}
