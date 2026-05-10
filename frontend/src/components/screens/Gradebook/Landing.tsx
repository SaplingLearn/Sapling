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

const CARD_HEIGHT = 244;
const BAND_HEIGHT = 132;

function percentColor(percent: number | null): string {
  if (percent === null) return "var(--text-muted)";
  if (percent >= 90) return "#4e873c";
  if (percent >= 80) return "#b4862c";
  if (percent >= 70) return "#b4562c";
  if (percent >= 60) return "#a8456b";
  return "#a83a3a";
}

const DiscsWatermark = () => (
  <svg
    viewBox="0 0 240 160"
    preserveAspectRatio="xMaxYMid slice"
    aria-hidden="true"
    style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
  >
    <circle cx="190" cy="40" r="54" fill="rgba(255,255,255,0.10)" />
    <circle cx="230" cy="110" r="38" fill="rgba(255,255,255,0.10)" />
    <circle cx="178" cy="96" r="14" fill="rgba(0,0,0,0.06)" />
  </svg>
);

export function GradebookLanding() {
  const { userId, userReady } = useUser();
  const toast = useToast();

  const [semesters, setSemesters] = React.useState<string[]>([]);
  const [selected, setSelected] = React.useState<string>("");
  const [courses, setCourses] = React.useState<GradebookCourseSummary[]>([]);
  const [colorMap, setColorMap] = React.useState<Record<string, string>>({});
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
        const colors: Record<string, string> = {};
        for (const c of all) {
          if (c.color) colors[c.course_id] = c.color;
        }
        setColorMap(colors);
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
              gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
              gap: 16,
            }}
          >
            {courses.map((c) => {
              const courseColor = colorMap[c.course_id] || "var(--accent)";
              const isPlaceholder = c.letter == null;
              return (
                <Link
                  key={c.course_id}
                  href={`/gradebook/${encodeURIComponent(c.course_id)}`}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    border: "1px solid rgba(42, 39, 31, 0.10)",
                    borderRadius: 12,
                    background: "var(--bg-panel)",
                    textDecoration: "none",
                    color: "var(--text)",
                    overflow: "hidden",
                    height: CARD_HEIGHT,
                    boxShadow: "0 1px 2px rgba(19, 38, 16, 0.04)",
                    transition:
                      "transform var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease)",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = "translateY(-2px)";
                    e.currentTarget.style.borderColor = "rgba(42, 39, 31, 0.18)";
                    e.currentTarget.style.boxShadow =
                      "0 6px 18px rgba(42, 39, 31, 0.10)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = "";
                    e.currentTarget.style.borderColor = "rgba(42, 39, 31, 0.10)";
                    e.currentTarget.style.boxShadow =
                      "0 1px 2px rgba(19, 38, 16, 0.04)";
                  }}
                >
                  <div
                    style={{
                      background: courseColor,
                      color: "#ffffff",
                      height: BAND_HEIGHT,
                      padding: "14px 18px",
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "space-between",
                      alignItems: "flex-start",
                      gap: 14,
                      position: "relative",
                      overflow: "hidden",
                    }}
                  >
                    <DiscsWatermark />
                    <div
                      className="mono"
                      style={{
                        position: "relative",
                        zIndex: 1,
                        fontSize: 10.5,
                        fontWeight: 600,
                        letterSpacing: "0.14em",
                        textTransform: "uppercase",
                        color: "#ffffff",
                        opacity: 0.92,
                      }}
                    >
                      {c.course_code}
                    </div>
                    <span
                      style={{
                        position: "relative",
                        zIndex: 1,
                        display: "inline-block",
                        color: "#ffffff",
                        fontFamily:
                          "var(--font-display), 'Playfair Display', Georgia, serif",
                        fontWeight: isPlaceholder ? 400 : 500,
                        fontStyle: isPlaceholder ? "italic" : "normal",
                        fontSize: 64,
                        lineHeight: 0.9,
                        letterSpacing: "-0.02em",
                        opacity: isPlaceholder ? 0.6 : 1,
                      }}
                    >
                      {isPlaceholder ? "—" : c.letter}
                    </span>
                  </div>
                  <div
                    style={{
                      padding: "12px 16px 14px",
                      flex: 1,
                      display: "flex",
                      flexDirection: "column",
                    }}
                  >
                    <div
                      style={{
                        fontFamily:
                          "var(--font-display), 'Playfair Display', Georgia, serif",
                        fontWeight: 500,
                        fontSize: 18,
                        lineHeight: 1.25,
                        letterSpacing: "-0.01em",
                        color: "var(--text)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        display: "-webkit-box",
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: "vertical",
                      }}
                    >
                      {c.course_name}
                    </div>
                    <div style={{ flex: 1, minHeight: 8 }} />
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "baseline",
                        gap: 8,
                      }}
                    >
                      <span
                        className="mono"
                        style={{
                          fontSize: 18,
                          fontWeight: 600,
                          lineHeight: 1,
                          letterSpacing: "-0.02em",
                          color: percentColor(c.percent),
                        }}
                      >
                        {c.percent === null
                          ? "No grades"
                          : `${c.percent.toFixed(1)}%`}
                      </span>
                      <span
                        className="mono"
                        style={{
                          fontSize: 11,
                          letterSpacing: "0.02em",
                          color: "var(--text-dim)",
                        }}
                      >
                        {c.graded_count}/{c.total_count} graded
                      </span>
                    </div>
                  </div>
                </Link>
              );
            })}
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
