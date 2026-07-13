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
import { getGradebookSummary, getCourses } from "@/lib/api";
import type { EnrolledCourse } from "@/lib/api";
import type { GradebookCourseSummary } from "@/lib/types";
import { SyllabusUploadFlow } from "@/components/Gradebook/SyllabusUploadFlow";
import { Button } from "@/components/ui";

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

  const [semesters, setSemesters] = React.useState<string[]>([]);
  const [selected, setSelected] = React.useState<string>("");
  const [courses, setCourses] = React.useState<GradebookCourseSummary[]>([]);
  const [colorMap, setColorMap] = React.useState<Record<string, string>>({});
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
        const colors: Record<string, string> = {};
        for (const c of all) {
          if (c.color) colors[c.course_id] = c.color;
        }
        setColorMap(colors);
      })
      .catch(() => {
        setSemesters(SAMPLE_SEMESTERS);
        setSelected(SAMPLE_SEMESTERS[0]);
      });
  }, [userId]);

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
        setCourses(res.courses.length ? res.courses : []);
      })
      .catch(() => {
        setCourses([]);
      })
      .finally(() => setLoading(false));
  }, [userId, selected]);

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

    let nextIdx: number;
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
          <Button variant="primary" size="sm" onClick={() => setUploadOpen(true)}>
            Upload syllabus
          </Button>
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
        {loading ? (
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
