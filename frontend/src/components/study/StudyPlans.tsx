"use client";

import React, { useState } from "react";
import { useUser } from "@/context/UserContext";
import type { EnrolledCourse } from "@/lib/api";
import { PageHeading, SaplingSurface } from "@/components/sapling";
import { StudyPlanPanel } from "../StudyPlanPanel";
import { SavedStudyGuides } from "./SavedStudyGuides";

export function StudyPlans({ courses, initialCourseId = "", initialDocumentId = "" }: {
  courses: EnrolledCourse[]; initialCourseId?: string; initialDocumentId?: string;
}) {
  const { userId, userReady } = useUser();
  const [selected, setSelected] = useState(initialCourseId);
  const byId = new Map(courses.map((course) => [course.course_id, course]));
  const courseId = byId.has(selected) ? selected : courses[0]?.course_id || "";
  const course = byId.get(courseId);
  return <SaplingSurface><section style={{ width: "100%", minWidth: 0, padding: "24px clamp(16px, 4vw, 40px)", background: "var(--sapling-paper)", color: "var(--sapling-ink)" }} data-testid="study-plans-page">
    <PageHeading title="Everything you need to prepare." eyebrow="Study guide" level={2}
      description="One assessment, one workspace: what to learn, when to study, and how you’re progressing." />
    <label style={{ display: "grid", gap: 8, margin: "24px 0", maxWidth: 400 }}>Course
      <select aria-label="Study plan course" data-testid="study-plan-course" value={courseId} disabled={!userReady} onChange={(e) => setSelected(e.target.value)} style={{ padding: 12, font: "inherit", border: "1px solid var(--sapling-line)", borderRadius: 6, background: "var(--sapling-white)" }}>
        {!courseId && <option value="">Choose a course</option>}
        {[...byId.values()].map((item) => <option key={item.course_id} value={item.course_id}>{item.course_code || item.course_name}</option>)}
      </select>
    </label>
    {userReady && course ? <StudyPlanPanel key={`plan:${userId}:${courseId}`} userId={userId} courseId={courseId}
      expanded initialDocumentId={courseId === initialCourseId ? initialDocumentId : ""} /> : <p>{userReady ? "Enroll in a course to create a study plan." : "Loading your courses…"}</p>}
    {userReady && <SavedStudyGuides key={`history:${userId}:${courseId}`} userId={userId} courseId={courseId} semester="" />}
  </section></SaplingSurface>;
}
