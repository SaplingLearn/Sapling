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

export function GradebookLanding() {
  const { userId, userReady } = useUser();
  const toast = useToast();

  const [semesters, setSemesters] = React.useState<string[]>([]);
  const [selected, setSelected] = React.useState<string>("");
  const [courses, setCourses] = React.useState<GradebookCourseSummary[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [uploadOpen, setUploadOpen] = React.useState(false);

  React.useEffect(() => {
    if (!userId) return;
    getCourses(userId)
      .then((res) => {
        const all = res.courses as (EnrolledCourse & { semester?: string })[];
        const distinct = Array.from(
          new Set(all.map((c) => (c as any).semester).filter(Boolean)),
        ) as string[];
        const list = distinct.length ? distinct : ["Spring 2026"];
        setSemesters(list);
        setSelected(list[0]);
      })
      .catch((err) => toast.error(`Could not load courses: ${err.message}`));
  }, [userId, toast]);

  React.useEffect(() => {
    if (!userId || !selected) return;
    setLoading(true);
    getGradebookSummary(userId, selected)
      .then((res) => setCourses(res.courses))
      .catch((err) => toast.error(`Gradebook failed to load: ${err.message}`))
      .finally(() => setLoading(false));
  }, [userId, selected, toast]);

  if (!userReady) return null;

  return (
    <>
      <TopBar
        title="Gradebook"
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
