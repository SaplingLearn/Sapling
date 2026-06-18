"use client";
import React from "react";
import { TopBar } from "@/components/TopBar";
import { SemesterChips } from "@/components/Gradebook/SemesterChips";
import {
  CourseCard,
  COURSE_CARD_GRID_GAP,
  COURSE_CARD_HEIGHT,
} from "@/components/Gradebook/CourseCard";
import { AmbientOrbs } from "@/components/Gradebook/AmbientOrbs";
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
  const [colorMap, setColorMap] = React.useState<Record<string, string>>({});
  const [loading, setLoading] = React.useState(true);
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [coursesError, setCoursesError] = React.useState<string | null>(null);

  const fetchCourses = React.useCallback(() => {
    if (!userId) return;
    setCoursesError(null);
    getCourses(userId)
      .then((res) => {
        const all = res.courses as (EnrolledCourse & { semester?: string })[];
        const distinct = Array.from(
          new Set(all.map((c) => (c as any).semester).filter(Boolean)),
        ) as string[];
        const list = distinct.length ? distinct : ["Spring 2026"];
        setSemesters(list);
        setSelected(list[0]);
        const colors: Record<string, string> = {};
        for (const c of all) {
          if (c.color) colors[c.course_id] = c.color;
        }
        setColorMap(colors);
      })
      .catch((err) => {
        setCoursesError(err.message || "Unknown error");
        toast.error(`Could not load courses: ${err.message}`);
      });
  }, [userId, toast]);

  React.useEffect(() => {
    fetchCourses();
  }, [fetchCourses]);

  React.useEffect(() => {
    if (!userId || !selected) return;
    setLoading(true);
    getGradebookSummary(userId, selected)
      .then((res) => setCourses(res.courses))
      .catch((err) => toast.error(`Gradebook failed to load: ${err.message}`))
      .finally(() => setLoading(false));
  }, [userId, selected, toast]);

  const gridRef = React.useRef<HTMLDivElement>(null);

  const handleGridKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!gridRef.current) return;
    const anchors = Array.from(
      gridRef.current.querySelectorAll<HTMLAnchorElement>("a"),
    );
    if (anchors.length === 0) return;

    // Number keys 1-9: jump to that course by position
    if (/^[1-9]$/.test(e.key)) {
      const idx = parseInt(e.key, 10) - 1;
      if (idx < anchors.length) {
        anchors[idx].focus();
        e.preventDefault();
      }
      return;
    }

    const active = document.activeElement;
    const idx = anchors.indexOf(active as HTMLAnchorElement);
    if (idx === -1) return;

    let nextIdx = idx;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      nextIdx = Math.min(idx + 1, anchors.length - 1);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      nextIdx = Math.max(idx - 1, 0);
    } else if (e.key === "Home") {
      nextIdx = 0;
    } else if (e.key === "End") {
      nextIdx = anchors.length - 1;
    } else {
      return;
    }
    anchors[nextIdx].focus();
    e.preventDefault();
  };

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
              color: "var(--accent-fg)",
              fontSize: 13,
              border: 0,
              cursor: "pointer",
            }}
          >
            Upload syllabus
          </button>
        }
      />
      <main
        style={{
          padding: "var(--pad-xl)",
          position: "relative",
          overflow: "hidden",
          minHeight: "calc(100vh - var(--row-h))",
        }}
      >
        <AmbientOrbs />
        <div style={{ position: "relative", zIndex: 1 }}>
        <SemesterChips
          semesters={semesters}
          selected={selected}
          onSelect={setSelected}
        />
        {coursesError ? (
          <ErrorBanner message={coursesError} onRetry={fetchCourses} />
        ) : loading ? (
          <LoadingSkeleton />
        ) : courses.length === 0 ? (
          <EmptyState semesterLabel={selected} onUpload={() => setUploadOpen(true)} />
        ) : (
          <div
            ref={gridRef}
            onKeyDown={handleGridKeyDown}
            role="grid"
            aria-label="Courses"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
              gap: COURSE_CARD_GRID_GAP,
            }}
          >
            {courses.map((c) => (
              <CourseCard
                key={c.course_id}
                course={c}
                variant="default"
                courseColor={colorMap[c.course_id] || "var(--accent)"}
              />
            ))}
          </div>
        )}
        </div>
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

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      style={{
        padding: "20px 24px",
        borderRadius: "var(--r-md)",
        background: "var(--err-soft)",
        border: "1px solid color-mix(in oklab, var(--err) 20%, transparent)",
        display: "flex",
        gap: 16,
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
      }}
    >
      <div>
        <div style={{ fontWeight: 600, color: "var(--err)", marginBottom: 4 }}>
          We couldn&apos;t load your courses.
        </div>
        <div style={{ fontSize: 13, color: "var(--text-dim)" }}>{message}</div>
      </div>
      <button
        type="button"
        className="btn btn--primary"
        onClick={onRetry}
        style={{ padding: "8px 16px" }}
      >
        Try again
      </button>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div
      aria-hidden="true"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
        gap: COURSE_CARD_GRID_GAP,
      }}
    >
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="skeleton"
          style={{ height: COURSE_CARD_HEIGHT, borderRadius: "var(--r-md)" }}
        />
      ))}
    </div>
  );
}

function EmptyState({
  semesterLabel,
  onUpload,
}: {
  semesterLabel: string;
  onUpload: () => void;
}) {
  return (
    <div style={{ padding: "64px 8px 40px", maxWidth: 680 }}>
      <div
        className="mono"
        style={{
          fontSize: 11,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "var(--text-muted)",
          marginBottom: 14,
        }}
      >
        {semesterLabel || "This semester"}
      </div>
      <h2
        style={{
          fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
          fontWeight: 500,
          fontSize: 56,
          lineHeight: 1.05,
          letterSpacing: "-0.02em",
          color: "var(--text)",
          margin: "0 0 18px",
        }}
      >
        A blank semester, ready to plant.
      </h2>
      <p
        style={{
          fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
          fontSize: 17,
          lineHeight: 1.6,
          color: "var(--text-dim)",
          margin: "0 0 32px",
          maxWidth: 540,
        }}
      >
        Drop in a syllabus and Sapling lays out every assignment, due date, and
        weight, so you can see what&apos;s coming, not just what already happened.
      </p>
      <button
        type="button"
        className="btn btn--primary"
        onClick={onUpload}
        style={{ padding: "10px 18px", fontSize: 14 }}
      >
        Upload syllabus
      </button>
    </div>
  );
}
