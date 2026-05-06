"use client";
import { TopBar } from "@/components/TopBar";
import { Icon } from "@/components/Icon";

export default function CoursePlannerPage() {
  return (
    <div style={{ display: "flex", height: "100vh", flexDirection: "column" }}>
      <TopBar title="Course Planner" />
      <main
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: 32,
          gap: 14,
          textAlign: "center",
        }}
      >
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "6px 14px",
            borderRadius: "var(--r-full)",
            background: "var(--accent-soft)",
            color: "var(--accent)",
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
        >
          <Icon name="sparkle" size={12} />
          Coming soon
        </div>
        <div className="h-serif" style={{ fontSize: 28, fontWeight: 500 }}>
          Course Planner
        </div>
        <div style={{ color: "var(--text-dim)", fontSize: 14, maxWidth: 480, lineHeight: 1.55 }}>
          Plan semesters, map prerequisites, and project your degree timeline. We&apos;re still
          building it — check back soon.
        </div>
      </main>
    </div>
  );
}
