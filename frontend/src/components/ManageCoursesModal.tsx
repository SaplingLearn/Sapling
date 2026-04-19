"use client";

import React from "react";
import { createPortal } from "react-dom";
import { Icon } from "./Icon";
import { useToast } from "./ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import {
  addCourse,
  deleteCourse,
  updateCourseColor,
  onboardingCoursesSearch,
  type EnrolledCourse,
  type OnboardingCourse,
} from "@/lib/api";

const COLOR_RE = /^#[0-9a-fA-F]{6}$/;

const DEFAULT_COLORS = [
  "#4e873c", "#3e6f8a", "#b4562c", "#7b4b99",
  "#b4862c", "#a8456b", "#3a7f77", "#3f3b31",
];

interface Props {
  open: boolean;
  userId: string;
  courses: EnrolledCourse[];
  onClose: () => void;
  onChanged: () => Promise<void> | void;
}

export function ManageCoursesModal({ open, userId, courses, onClose, onChanged }: Props) {
  const toast = useToast();
  const [query, setQuery] = React.useState("");
  const [results, setResults] = React.useState<OnboardingCourse[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => setMounted(true), []);

  React.useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handler);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  React.useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => {
      setLoading(true);
      onboardingCoursesSearch(query)
        .then(r => setResults(r.courses ?? []))
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 200);
    return () => clearTimeout(t);
  }, [query, open]);

  const enrolledIds = React.useMemo(() => new Set(courses.map(c => c.course_id)), [courses]);

  const handleAdd = async (course: OnboardingCourse) => {
    try {
      const color = DEFAULT_COLORS[courses.length % DEFAULT_COLORS.length];
      await addCourse(userId, course.id, color);
      toast.success(`Added ${course.course_code || course.course_name}`);
      await onChanged();
    } catch (err) {
      toast.error(`Failed to add course: ${String(err)}`);
    }
  };

  if (!open || !mounted) return null;

  return createPortal(
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(19,38,16,0.45)",
        zIndex: 200, display: "grid", placeItems: "center", padding: 20,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        className="card slide-up"
        style={{ width: "min(620px, 100%)", maxHeight: "80vh", overflow: "hidden", padding: 0, display: "flex", flexDirection: "column" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 20px", borderBottom: "1px solid var(--border)" }}>
          <div>
            <div className="label-micro">Manage</div>
            <div className="h-serif" style={{ fontSize: 20 }}>My Courses</div>
          </div>
          <button className="btn btn--ghost btn--sm" onClick={onClose} aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>

        <div style={{ padding: 20, overflowY: "auto" }}>
          <div className="label-micro" style={{ marginBottom: 8 }}>Your courses</div>
          {courses.length === 0 && (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No courses enrolled yet.</div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 20 }}>
            {courses.map(c => (
              <EnrolledRow key={c.course_id} userId={userId} course={c} onChanged={onChanged} />
            ))}
          </div>

          <div className="label-micro" style={{ marginBottom: 8 }}>Add a course</div>
          <div style={{ position: "relative", marginBottom: 10 }}>
            <input
              autoFocus
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search by code or name (e.g. MATH 242)"
              style={{
                width: "100%", padding: "8px 12px",
                border: "1px solid var(--border)", borderRadius: "var(--r-sm)",
                background: "var(--bg-input)", fontSize: 13,
              }}
            />
          </div>
          <div style={{ border: "1px solid var(--border)", borderRadius: "var(--r-sm)", maxHeight: 220, overflowY: "auto" }}>
            {loading && <div style={{ padding: 12, fontSize: 12, color: "var(--text-muted)" }}>Searching…</div>}
            {!loading && results.length === 0 && (
              <div style={{ padding: 12, fontSize: 12, color: "var(--text-muted)" }}>No matches.</div>
            )}
            {!loading && results.map(c => {
              const enrolled = enrolledIds.has(c.id);
              return (
                <div
                  key={c.id}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "8px 12px", borderBottom: "1px solid var(--border)", fontSize: 13,
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 500 }}>{c.course_code}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{c.course_name}</div>
                  </div>
                  <button
                    className="btn btn--sm"
                    disabled={enrolled}
                    onClick={() => handleAdd(c)}
                    style={{
                      opacity: enrolled ? 0.55 : 1,
                      background: enrolled ? "var(--bg-subtle)" : undefined,
                    }}
                  >
                    {enrolled ? "Enrolled" : <><Icon name="plus" size={12} /> Add</>}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function EnrolledRow({
  userId, course, onChanged,
}: {
  userId: string;
  course: EnrolledCourse;
  onChanged: () => Promise<void> | void;
}) {
  const toast = useToast();
  const [color, setColor] = React.useState(course.color || DEFAULT_COLORS[0]);
  const [dirty, setDirty] = React.useState(false);
  const valid = COLOR_RE.test(color);

  React.useEffect(() => {
    setColor(course.color || DEFAULT_COLORS[0]);
    setDirty(false);
  }, [course.color]);

  const saveColor = async () => {
    if (!valid || !dirty) return;
    try {
      await updateCourseColor(userId, course.course_id, color);
      toast.success("Color updated");
      setDirty(false);
      await onChanged();
    } catch (err) {
      toast.error(`Failed: ${String(err)}`);
    }
  };

  const doDelete = async () => {
    try {
      await deleteCourse(userId, course.course_id);
      toast.success(`Removed ${course.course_code || course.course_name}`);
      await onChanged();
    } catch (err) {
      toast.error(`Failed: ${String(err)}`);
    }
  };

  const del = useConfirm(doDelete);

  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "8px 10px", border: "1px solid var(--border)", borderRadius: "var(--r-sm)",
        background: "var(--bg-subtle)",
      }}
    >
      <div style={{ position: "relative", width: 24, height: 24, flexShrink: 0 }}>
        <input
          type="color"
          value={valid ? color : "#888888"}
          onChange={e => { setColor(e.target.value); setDirty(true); }}
          onBlur={saveColor}
          aria-label={`Color for ${course.course_name}`}
          style={{
            position: "absolute", inset: 0, opacity: 0, cursor: "pointer", width: "100%", height: "100%",
          }}
        />
        <span
          aria-hidden
          style={{
            display: "block", width: 24, height: 24, borderRadius: "50%",
            background: valid ? color : "var(--bg-soft)",
            border: "1px solid var(--border-strong)",
          }}
        />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{course.course_code || course.course_name}</div>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {course.course_code ? course.course_name : ""} · {course.node_count} concepts
        </div>
      </div>
      <input
        value={color}
        onChange={e => { setColor(e.target.value); setDirty(true); }}
        onBlur={saveColor}
        onKeyDown={e => { if (e.key === "Enter") saveColor(); }}
        className="mono"
        style={{
          width: 84, padding: "4px 6px",
          border: `1px solid ${valid ? "var(--border)" : "var(--err)"}`,
          borderRadius: "var(--r-xs)", background: "var(--bg-input)", fontSize: 11,
        }}
      />
      <button
        onClick={del.trigger}
        className={`btn btn--sm ${del.armed ? "btn--danger" : "btn--ghost"}`}
        style={del.armed ? { background: "var(--err-soft)", color: "var(--err)" } : undefined}
        title={del.armed ? "Click again to confirm" : "Remove course"}
      >
        {del.armed ? "Click again" : <Icon name="x" size={12} />}
      </button>
    </div>
  );
}
