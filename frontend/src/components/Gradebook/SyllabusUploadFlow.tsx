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
import { humanizeError } from "@/lib/errorMessage";
import type { ExtractedSyllabusCategory } from "@/lib/types";
import { cn } from "@/lib/cn";

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

  // Run token (#770): one per dialog opening, bumped again by a cancel. An
  // upload or course list from a previous opening (or a cancelled upload)
  // must never jump the current dialog to `review` with another file's data.
  const runRef = React.useRef(0);
  // Read through a ref so the per-opening reset below keys on the opening
  // alone — a toast identity change must never re-run it mid-dialog.
  const toastRef = React.useRef(toast);
  React.useEffect(() => { toastRef.current = toast; }, [toast]);

  React.useEffect(() => {
    if (!open) return;
    const run = ++runRef.current;
    setStep("pick-course"); setCourseId(""); setDocId(""); setCategories([]); setAssignments([]);
    getCourses(userId)
      .then((res) => {
        if (run === runRef.current) setCourses(res.courses);
      })
      .catch((err: unknown) => {
        if (run !== runRef.current) return;
        setCourses([]);
        toastRef.current.error(`Couldn't load your courses: ${humanizeError(err, "Try again.")}`);
      });
    // Closing ends this opening's run: anything still in flight is stale.
    const runs = runRef;
    return () => { runs.current++; };
  }, [open, userId]);

  const total = categories.reduce((s, c) => s + Number(c.weight || 0), 0);
  const weightsValid = categories.length === 0 || Math.abs(total - 100) <= 0.5;

  const handleFile = async (file: File) => {
    if (!courseId) {
      toast.error("Pick a course first");
      return;
    }
    const run = ++runRef.current;
    setStep("upload");
    try {
      const res = await uploadSyllabus({ userId, courseId, file });
      if (run !== runRef.current) return;
      setDocId(res.doc_id ?? res.id);
      setCategories(res.categories ?? []);
      setAssignments(res.assignments ?? []);
      setStep("review");
    } catch (err: unknown) {
      if (run !== runRef.current) return;
      toast.error(`Upload failed: ${humanizeError(err, "Try again.")}`);
      setStep("pick-course");
    }
  };

  // Abandons the extraction client-side: the request can't be aborted (the
  // upload helper takes no signal), so its answer is discarded on arrival.
  const cancelUpload = () => {
    runRef.current++;
    setStep("pick-course");
  };

  const handleSave = async () => {
    const run = runRef.current;
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
      // The write landed either way, so it is always reported; only the
      // navigation belongs to the opening that started it.
      toast.success("Syllabus applied");
      if (run !== runRef.current) return;
      router.push(`/gradebook/${encodeURIComponent(courseId)}`);
      onClose();
    } catch (err: unknown) {
      toast.error(`Save failed: ${humanizeError(err, "Try again.")}`);
      if (run === runRef.current) setStep("review");
    }
  };

  return (
    // Not dismissible while saving: the apply is a write that can't be
    // cancelled, and closing would hide whether it landed.
    <Dialog open={open} onClose={onClose} dismissible={step !== "saving"} title="Upload syllabus" size="lg" padding="20px">
      {step === "pick-course" && (
        <>
          <label>
            Course
            <select
              value={courseId}
              onChange={(e) => setCourseId(e.target.value)}
              className="w-full p-1.5 border border-border rounded-sm"
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
            className="mt-3 max-w-full"
          />
        </>
      )}

      {step === "upload" && (
        <>
          <p className="text-text-dim">Extracting syllabus…</p>
          <div className="flex justify-end">
            <button type="button" onClick={cancelUpload}>Cancel upload</button>
          </div>
        </>
      )}

      {step === "review" && (
        <>
          <h4 className="mt-0">Categories</h4>
          <ul className="list-none m-0 p-0">
            {categories.map((c, i) => (
              <li key={i} className="flex gap-2 mb-1.5">
                <input
                  value={c.name}
                  onChange={(e) =>
                    setCategories((arr) =>
                      arr.map((x, idx) => (idx === i ? { ...x, name: e.target.value } : x)),
                    )
                  }
                  className="flex-1 min-w-0 p-1.5 border border-border rounded-sm"
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
                  className="w-17.5 shrink-0 p-1.5 border border-border rounded-sm"
                />
                <span className="self-center">%</span>
                <button type="button" onClick={() =>
                  setCategories((arr) => arr.filter((_, idx) => idx !== i))
                }>✕</button>
              </li>
            ))}
          </ul>
          <button type="button" onClick={() =>
            setCategories((arr) => [...arr, { name: "", weight: 0 }])
          }>+ Add category</button>
          <p className={cn("text-sm", weightsValid ? "text-accent" : "text-err")}>
            Total: {total.toFixed(1)}% {weightsValid ? "✓" : "(need 100%)"}
          </p>

          <h4>Assignments ({assignments.length})</h4>
          <ul className="list-none m-0 p-0 max-h-50 overflow-auto">
            {assignments.map((a, i) => (
              <li key={i} className="flex flex-wrap gap-2 py-1 px-0">
                <input
                  value={a.title}
                  onChange={(e) =>
                    setAssignments((arr) =>
                      arr.map((x, idx) => (idx === i ? { ...x, title: e.target.value } : x)),
                    )
                  }
                  className="flex-1 min-w-30 p-1 border border-border rounded-xs"
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
                  className="p-1 border border-border rounded-xs"
                />
                <button type="button" onClick={() =>
                  setAssignments((arr) => arr.filter((_, idx) => idx !== i))
                }>✕</button>
              </li>
            ))}
          </ul>

          <div className="mt-4 flex flex-wrap justify-end gap-2">
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
        <p className="text-text-dim">Saving…</p>
      )}
    </Dialog>
  );
}
