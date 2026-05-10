"use client";
import React from "react";
import Link from "next/link";
import { TopBar } from "@/components/TopBar";
import { SemesterChips } from "@/components/Gradebook/SemesterChips";
import { useUser } from "@/context/UserContext";
import { useToast } from "@/components/ToastProvider";
import { getGradebookSummary, getCourses } from "@/lib/api";
import type { EnrolledCourse } from "@/lib/api";
import type { GradebookCourseSummary } from "@/lib/types";
import { SyllabusUploadFlow } from "@/components/Gradebook/SyllabusUploadFlow";

const SAMPLE_SEMESTERS = ["Spring 2026", "Fall 2025"];
const SAMPLE_COURSES: Record<string, GradebookCourseSummary[]> = {
  "Spring 2026": [
    {
      course_id: "sample-bio-101",
      course_code: "BIO-101",
      course_name: "Biology",
      semester: "Spring 2026",
      percent: 91.2,
      letter: "A-",
      graded_count: 8,
      total_count: 12,
    },
    {
      course_id: "sample-mat-220",
      course_code: "MAT-220",
      course_name: "Linear Algebra",
      semester: "Spring 2026",
      percent: 84.5,
      letter: "B",
      graded_count: 6,
      total_count: 10,
    },
    {
      course_id: "sample-eng-201",
      course_code: "ENG-201",
      course_name: "English Lit",
      semester: "Spring 2026",
      percent: 88.0,
      letter: "B+",
      graded_count: 4,
      total_count: 7,
    },
    {
      course_id: "sample-chem-200",
      course_code: "CHEM-200",
      course_name: "Chemistry",
      semester: "Spring 2026",
      percent: 76.3,
      letter: "C+",
      graded_count: 5,
      total_count: 9,
    },
    {
      course_id: "sample-his-101",
      course_code: "HIS-101",
      course_name: "World History",
      semester: "Spring 2026",
      percent: null,
      letter: null,
      graded_count: 0,
      total_count: 5,
    },
  ],
  "Fall 2025": [
    {
      course_id: "sample-psy-110",
      course_code: "PSY-110",
      course_name: "Intro to Psychology",
      semester: "Fall 2025",
      percent: 93.4,
      letter: "A",
      graded_count: 14,
      total_count: 14,
    },
    {
      course_id: "sample-cs-101",
      course_code: "CS-101",
      course_name: "Intro to Computer Science",
      semester: "Fall 2025",
      percent: 87.1,
      letter: "B+",
      graded_count: 11,
      total_count: 12,
    },
  ],
};

export function GradebookLanding() {
  const { userId, userReady } = useUser();
  const toast = useToast();

  const [semesters, setSemesters] = React.useState<string[]>([]);
  const [selected, setSelected] = React.useState<string>("");
  const [courses, setCourses] = React.useState<GradebookCourseSummary[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [uploadOpen, setUploadOpen] = React.useState(false);

  React.useEffect(() => {
    if (!userId) {
      setSemesters(SAMPLE_SEMESTERS);
      setSelected(SAMPLE_SEMESTERS[0]);
      return;
    }
    getCourses(userId)
      .then((res) => {
        const all = res.courses as (EnrolledCourse & { semester?: string })[];
        const distinct = Array.from(
          new Set(all.map((c) => (c as any).semester).filter(Boolean)),
        ) as string[];
        const list = distinct.length ? distinct : SAMPLE_SEMESTERS;
        setSemesters(list);
        setSelected(list[0]);
      })
      .catch(() => {
        setSemesters(SAMPLE_SEMESTERS);
        setSelected(SAMPLE_SEMESTERS[0]);
      });
  }, [userId, toast]);

  React.useEffect(() => {
    if (!selected) return;
    if (!userId) {
      setCourses(SAMPLE_COURSES[selected] ?? []);
      setLoading(false);
      return;
    }
    setLoading(true);
    getGradebookSummary(userId, selected)
      .then((res) => {
        setCourses(res.courses.length ? res.courses : (SAMPLE_COURSES[selected] ?? []));
      })
      .catch(() => {
        setCourses(SAMPLE_COURSES[selected] ?? []);
      })
      .finally(() => setLoading(false));
  }, [userId, selected, toast]);

  if (!userReady) return null;

  return (
    <>
      <TopBar
        title="Grades"
        actions={
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            style={{
              padding: "6px 12px",
              borderRadius: "var(--r-sm)",
              background: "var(--accent)",
              color: "#fff",
              fontSize: 13,
              border: 0,
              cursor: "pointer",
            }}
          >
            Upload syllabus
          </button>
        }
      />
      <main style={{ padding: 32 }}>
        <SemesterChips
          semesters={semesters}
          selected={selected}
          onSelect={setSelected}
        />
        {loading ? (
          <p style={{ color: "var(--text-dim)" }}>Loading…</p>
        ) : courses.length === 0 ? (
          <p style={{ color: "var(--text-dim)" }}>
            No courses enrolled for {selected}. Add a course in onboarding to get started.
          </p>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
              gap: 12,
            }}
          >
            {courses.map((c) => (
              <Link
                key={c.course_id}
                href={`/gradebook/${encodeURIComponent(c.course_id)}`}
                style={{
                  padding: 16,
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  background: "var(--bg)",
                  textDecoration: "none",
                  color: "var(--text)",
                  transition: "background var(--dur-fast) var(--ease)",
                }}
              >
                <div className="label-micro">{c.course_code}</div>
                <div style={{ fontWeight: 600, margin: "2px 0 6px" }}>
                  {c.course_name}
                </div>
                <div
                  style={{
                    fontSize: 22,
                    fontWeight: 700,
                    color: "var(--accent)",
                  }}
                >
                  {c.letter ?? "—"}
                </div>
                <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                  {c.percent !== null ? `${c.percent.toFixed(1)}%` : "No grades yet"} ·{" "}
                  {c.graded_count}/{c.total_count} graded
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>

      {userId && (
        <SyllabusUploadFlow
          open={uploadOpen}
          userId={userId}
          onClose={() => setUploadOpen(false)}
        />
      )}
    </>
  );
}
