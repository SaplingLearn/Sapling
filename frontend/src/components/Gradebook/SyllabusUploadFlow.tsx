"use client";
import React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui";
import Dialog from "@/components/Dialog";
import {
  uploadSyllabus, applySyllabus, getCourses,
} from "@/lib/api";
import type { EnrolledCourse } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import type { ExtractedSyllabusCategory } from "@/lib/types";

interface Props {
  open: boolean;
  userId: string;
  onClose: () => void;
}

interface ExtractedAssignment {
  title: string;
  due_date: string | null;
  assignment_type: string | null;
  notes: string | null;
}

type Step = "pick-course" | "upload" | "review" | "saving";

export function SyllabusUploadFlow({ open, userId, onClose }: Props) {
  const router = useRouter();
  const toast = useToast();
  const [step, setStep] = React.useState<Step>("pick-course");
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [courseId, setCourseId] = React.useState<string>("");
  const [docId, setDocId] = React.useState<string>("");
  const [categories, setCategories] = React.useState<ExtractedSyllabusCategory[]>([]);
  const [assignments, setAssignments] = React.useState<ExtractedAssignment[]>([]);

  React.useEffect(() => {
    if (!open) return;
    setStep("pick-course"); setCourseId(""); setDocId(""); setCategories([]); setAssignments([]);
    getCourses(userId).then((res) => setCourses(res.courses));
  }, [open, userId]);

  const total = categories.reduce((s, c) => s + Number(c.weight || 0), 0);
  const weightsValid = categories.length === 0 || Math.abs(total - 100) <= 0.5;

  const handleFile = async (file: File) => {
    if (!courseId) {
      toast.error("Pick a course first");
      return;
    }
    setStep("upload");
    try {
      const res = await uploadSyllabus({ userId, courseId, file });
      setDocId(res.doc_id ?? res.id);
      setCategories(res.categories ?? []);
      setAssignments(res.assignments ?? []);
      setStep("review");
    } catch (err: any) {
      toast.error(`Upload failed: ${err.message}`);
      setStep("pick-course");
    }
  };

  const handleSave = async () => {
    setStep("saving");
    try {
      await applySyllabus({
        userId,
        courseId,
        docId,
        categories: categories.map((c, i) => ({
          name: c.name, weight: c.weight, sort_order: i,
        })),
        assignments,
      });
      toast.success("Syllabus applied");
      router.push(`/gradebook/${encodeURIComponent(courseId)}`);
      onClose();
    } catch (err: any) {
      toast.error(`Save failed: ${err.message}`);
      setStep("review");
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Upload syllabus" size="lg" padding="20px">
      {step === "pick-course" && (
        <>
          <label>
            Course
            <select
              value={courseId}
              onChange={(e) => setCourseId(e.target.value)}
              style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
            >
              <option value="">Pick a course</option>
              {courses.map((c) => (
                <option key={c.course_id} value={c.course_id}>
                  {c.course_code} · {c.course_name}
                </option>
              ))}
            </select>
          </label>
          <input
            type="file"
            accept=".pdf,.docx,.pptx"
            disabled={!courseId}
            onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
            style={{ marginTop: 12, maxWidth: "100%" }}
          />
        </>
      )}

      {step === "upload" && (
        <p style={{ color: "var(--text-dim)" }}>Extracting syllabus…</p>
      )}

      {step === "review" && (
        <>
          <h4 style={{ marginTop: 0 }}>Categories</h4>
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {categories.map((c, i) => (
              <li key={i} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
                <input
                  value={c.name}
                  onChange={(e) =>
                    setCategories((arr) =>
                      arr.map((x, idx) => (idx === i ? { ...x, name: e.target.value } : x)),
                    )
                  }
                  style={{ flex: 1, minWidth: 0, padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
                />
                <input
                  type="number"
                  value={c.weight}
                  onChange={(e) =>
                    setCategories((arr) =>
                      arr.map((x, idx) =>
                        idx === i ? { ...x, weight: Number(e.target.value) } : x,
                      ),
                    )
                  }
                  style={{ width: 70, flexShrink: 0, padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
                />
                <span style={{ alignSelf: "center" }}>%</span>
                <button type="button" onClick={() =>
                  setCategories((arr) => arr.filter((_, idx) => idx !== i))
                }>✕</button>
              </li>
            ))}
          </ul>
          <button type="button" onClick={() =>
            setCategories((arr) => [...arr, { name: "", weight: 0 }])
          }>+ Add category</button>
          <p style={{ color: weightsValid ? "var(--accent)" : "var(--err)", fontSize: 12 }}>
            Total: {total.toFixed(1)}% {weightsValid ? "✓" : "(need 100%)"}
          </p>

          <h4>Assignments ({assignments.length})</h4>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, maxHeight: 200, overflow: "auto" }}>
            {assignments.map((a, i) => (
              <li key={i} style={{ display: "flex", flexWrap: "wrap", gap: 8, padding: "4px 0" }}>
                <input
                  value={a.title}
                  onChange={(e) =>
                    setAssignments((arr) =>
                      arr.map((x, idx) => (idx === i ? { ...x, title: e.target.value } : x)),
                    )
                  }
                  style={{ flex: 1, minWidth: 120, padding: 4, border: "1px solid var(--border)", borderRadius: 4 }}
                />
                <input
                  type="date"
                  value={a.due_date ?? ""}
                  onChange={(e) =>
                    setAssignments((arr) =>
                      arr.map((x, idx) =>
                        idx === i ? { ...x, due_date: e.target.value || null } : x,
                      ),
                    )
                  }
                  style={{ padding: 4, border: "1px solid var(--border)", borderRadius: 4 }}
                />
                <button type="button" onClick={() =>
                  setAssignments((arr) => arr.filter((_, idx) => idx !== i))
                }>✕</button>
              </li>
            ))}
          </ul>

          <div style={{ marginTop: 16, display: "flex", flexWrap: "wrap", justifyContent: "flex-end", gap: 8 }}>
            <button type="button" onClick={onClose}>Cancel</button>
            <Button
              variant="primary"
              size="sm"
              disabled={!weightsValid}
              onClick={handleSave}
            >
              Save to gradebook
            </Button>
          </div>
        </>
      )}

      {step === "saving" && (
        <p style={{ color: "var(--text-dim)" }}>Saving…</p>
      )}
    </Dialog>
  );
}
