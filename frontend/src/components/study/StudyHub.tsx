"use client";
/**
 * The Study hub: one page per course (design: "Sapling Study v2").
 *
 * This file is the orchestrator: it loads, gates on loading, and lays the
 * panels out. Every number is derived from real data in ./studyModel.ts and
 * ./hubModel.ts (see ./useHubView.ts); each panel is a file of its own.
 * Data sources (./useStudyData.ts):
 *   courses ............ getCourses (passed in, semester-scoped)
 *   concepts/edges ..... getGraph(userId, semester)
 *   exams/deadlines .... getAllAssignments (+ save/update/deleteAssignment)
 *   quiz history ....... listAttempts (GET /api/quiz/attempts)
 *   flashcards ......... getFlashcards
 *   study guides ....... getCachedStudyGuides
 *   daily minutes/goal . getStudyDaily / setStudyDailyGoal (routes/study.py)
 *   roadmap categories . getTopicChecklist, and refreshTopicChecklist when the
 *                        course has no current outline (routes/topic_checklist.py)
 *   exam coverage ...... the same checklist (a topic's assessments + node_id)
 *
 * Its three tool buttons leave for pages of their own (@/lib/toolHrefs):
 * Study Guide -> /study/guide, Flashcards -> /flashcards, Quiz -> /quiz.
 */
import React from "react";
import { useFlagMap } from "@/context/FlagsContext";
import { useUser } from "@/context/UserContext";
import type { EnrolledCourse } from "@/lib/api";
import type { ChecklistTopic } from "@/lib/topicChecklistApi";
import { StudyHubSkeleton } from "../Skeleton";
import { DailyGoalCard } from "./DailyGoalCard";
import { DatesEditorModal } from "./DatesEditorModal";
import { ExamTabs } from "./ExamTabs";
import { FocusCard, FocusEmpty } from "./FocusCard";
import { HubHeader } from "./HubHeader";
import { assessmentsForCourse, cardsFor, upcomingOf, type FlashcardRow } from "./hubModel";
import { SANS } from "./hubUi";
import { QuickReviews } from "./QuickReviews";
import { ReadinessBand } from "./ReadinessBand";
import { RecentActivity, RecentActivityModal } from "./RecentActivity";
import { Roadmap } from "./Roadmap";
import s from "./StudyHub.module.css";
import type { Assessment } from "./studyModel";
import { useDatesEditor, useSelectAddedExam } from "./useDatesEditor";
import { COURSE_PICKED, examPicked, useHubState, type HubState, type SetHub } from "./useHubState";
import { useHubView } from "./useHubView";
import { useConceptGraph, useCourseOutline, useStudyRecords, type StudyGraph, type StudyRecords } from "./useStudyData";
import { useToolNav } from "./useToolNav";

export interface StudyHubProps {
  courses: EnrolledCourse[];
  /** False until the course list has actually been fetched. An empty list
   *  means "no courses" only once this is true — before it, `courses` is just
   *  the initial `[]` and the "Add a course" empty state would be a lie. */
  coursesReady?: boolean;
  semester: string;
  semesterReady: boolean;
  initialCourseId?: string | null;
  isMobile: boolean;
  /** Test seam: a fixed "now". */
  today?: Date;
}

export function StudyHub({ courses, coursesReady = true, semester, semesterReady, initialCourseId, isMobile, today: todayProp }: StudyHubProps) {
  // hide_quiz (#620) hides Quiz everywhere it is offered:
  // shown only once the flags are in and it is not hidden.
  const { flags, ready: flagsReady } = useFlagMap();
  const quizShown = flagsReady && flags.hide_quiz !== "on";
  const { userId } = useUser();
  const today = React.useMemo(() => todayProp ?? new Date(), [todayProp]);

  const { graph, cards } = useConceptGraph(userId, semester, semesterReady);
  const records = useStudyRecords(userId);

  const [courseId, setCourseId] = React.useState<string>(initialCourseId || "");
  const course = courses.find(c => c.course_id === courseId) || courses[0] || null;
  const { st, set, closeTileMenu } = useHubState();
  const pickCourse = (id: string) => {
    setCourseId(id);
    set(COURSE_PICKED);
  };
  const { outline, reload: reloadOutline } = useCourseOutline(userId, course?.course_id || "", semester, semesterReady);

  // The hub paints nothing real until it knows the student's courses AND has
  // their concepts: without this it rendered the "Add a course" empty state,
  // then the chrome, then the roadmap, in three visible steps.
  if (!coursesReady || !semesterReady) return <StudyHubSkeleton isMobile={isMobile} />;
  if (!course) return <NoCourses />;
  if (!graph) return <StudyHubSkeleton isMobile={isMobile} />;

  return (
    <HubPage courses={courses} course={course} onPickCourse={pickCourse} userId={userId} today={today} isMobile={isMobile} quizShown={quizShown}
      graph={graph} cards={cards} records={records} outline={outline} reloadOutline={reloadOutline}
      st={st} set={set} closeTileMenu={closeTileMenu} />
  );
}

/** A student with no course this term: what the hub would show once they add one. */
function NoCourses() {
  return (
    <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)", fontFamily: SANS, color: "var(--text)", padding: 32 }}>
      <div style={{ textAlign: "center", maxWidth: 420 }}>
        <h1 className="h-serif" style={{ margin: 0, fontSize: 42, letterSpacing: "-0.02em" }}>Study</h1>
        <p style={{ fontSize: "var(--fs-base)", color: "var(--text-dim)" }}>Add a course to get a study roadmap, readiness for each exam, and quick reviews.</p>
      </div>
    </div>
  );
}

const HUB: React.CSSProperties = { color: "var(--text)", fontFamily: SANS, fontSize: "var(--fs-md)", lineHeight: 1.45, WebkitFontSmoothing: "antialiased" };

/** The hub for one course, once its concepts are in. */
function HubPage(props: {
  courses: EnrolledCourse[];
  course: EnrolledCourse;
  onPickCourse: (courseId: string) => void;
  userId: string;
  today: Date;
  isMobile: boolean;
  quizShown: boolean;
  graph: StudyGraph;
  cards: FlashcardRow[];
  records: StudyRecords;
  outline: ChecklistTopic[];
  /** Re-reads a course's outline after its exams changed. */
  reloadOutline: (courseId: string) => void;
  st: HubState;
  set: SetHub;
  closeTileMenu: (conceptId: string) => void;
}) {
  const { course, userId, today, isMobile, quizShown, records, st, set } = props;
  const cid = course.course_id;
  const view = useHubView({ course, graph: props.graph, cards: props.cards, records, outline: props.outline, st, today });
  const nav = useToolNav(cid, view.exam?.id ?? null);
  const editor = useDatesEditor({
    userId, courseId: cid, list: view.list, today,
    reload: records.reloadAssignments, onWritten: props.reloadOutline,
  });
  const selectExam = React.useCallback((id: string) => set(examPicked(id)), [set]);
  useSelectAddedExam(editor, view.exams, selectExam);

  /** Dated work still ahead for a course: the count on its picker row. */
  const upcomingIn = (id: string) => upcomingOf(assessmentsForCourse(records.assignments, id), today).length;
  const openDates = (withNewRow: boolean) => {
    editor.open(withNewRow);
    set({ menu: null });
  };
  /** A deadline in the bell: an exam or quiz selects its tab, homework has none. */
  const pickDeadline = (item: Assessment) =>
    set(item.type === "Homework" ? { menu: null } : { menu: null, exam: item.id, topic: null, lvl: null });
  /** A concept named on a Recent Activity row: select it, if it is still on the roadmap. */
  const pickConcept = (id: string) => {
    if (view.byId.has(id)) set({ topic: id, recentOpen: false });
  };
  const startReviews = () => nav.leaveTo(nav.cardsHref(view.reviews.map(x => x.t.name)));
  const { focus } = view;

  return (
    <div className={s.shell} style={{ background: "var(--bg)" }}>
      <div className={nav.leaving ? `${s.hub} ${s.leaving}` : s.hub} style={HUB}>
        <HubHeader courses={props.courses} courseId={cid} onPickCourse={props.onPickCourse} upcomingIn={upcomingIn}
          isMobile={isMobile} quizShown={quizShown} onTool={tool => nav.leaveTo(nav.toolHome(tool))} />

        <ExamTabs courseId={cid} courseLabel={view.label} exams={view.exams} exam={view.exam} upcoming={view.upcoming} soon={view.soon} today={today}
          bellOpen={st.menu === "bell"} onBell={open => set({ menu: open ? "bell" : null })}
          onSelectExam={selectExam} onPickDeadline={pickDeadline} onAdd={() => openDates(true)} onManage={() => openDates(false)} />

        {/* Re-keyed on the course and exam, so the band replays its entrance for each. */}
        <section aria-label="Readiness" key={`${cid}:${view.exam?.id ?? ""}`} className={`${s.areaReady} ${s.readyGrid} ${s.examEnter}`} style={{ padding: "16px 0", borderBottom: "1px solid var(--border)" }}>
          <ReadinessBand label={view.band.label} concepts={view.band.concepts} ready={view.ready}
            selectedId={view.sel?.id ?? null} level={st.lvl} onSelect={id => set({ topic: id })} onLevel={lvl => set({ lvl })} />
          {focus
            ? <FocusCard concept={focus} upNext={focus.id === view.rec?.id} prereqs={view.focusPrereqs}
                cardCount={cardsFor(view.cardCount, focus.name)} quizShown={quizShown} nav={nav} />
            : <FocusEmpty hasConcepts={view.topics.length > 0} />}
        </section>

        <Roadmap key={`roadmap:${cid}`} columns={view.columns} cards={view.cardCount} tileMenu={st.tileMenu} openCols={st.openCols}
          quizShown={quizShown} nav={nav} set={set} closeTileMenu={props.closeTileMenu} />

        {/* The 40px side bleed (padding + negative margin, in the stylesheet so
            the narrow layout can drop it) gives the Quick Reviews pop-up's drop
            shadow room to fade out; it sits in the 56px column gap. */}
        <aside aria-label="Activity" className={s.areaRail} style={{ display: "flex", flexDirection: "column" }}>
          <section aria-label="Daily goal" style={{ display: "flex", flexDirection: "column", gap: 10, paddingBottom: 24 }}>
            <DailyGoalCard daily={records.daily} onSave={records.saveGoal} />
            <QuickReviews reviews={view.reviews} courseLabel={view.label} onStart={startReviews} />
          </section>
          <RecentActivity rows={view.recent} onPickConcept={pickConcept} onShowAll={() => set({ recentOpen: true })} />
        </aside>

        {st.recentOpen && (
          <RecentActivityModal rows={view.recent} courseLabel={view.label} isMobile={isMobile}
            onPickConcept={pickConcept} onClose={() => set({ recentOpen: false })} />
        )}
        {editor.drafts && <DatesEditorModal editor={editor} drafts={editor.drafts} course={course} isMobile={isMobile} />}
      </div>
    </div>
  );
}
