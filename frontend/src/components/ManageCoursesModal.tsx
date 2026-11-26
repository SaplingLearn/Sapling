"use client";

import React from "react";
import { Icon } from "./Icon";
import { useToast } from "./ToastProvider";
import Dialog from "./Dialog";
import { useConfirm } from "@/lib/useConfirm";
import {
  addCourse,
  deleteCourse,
  updateCourseColor,
  onboardingCoursesSearch,
  type EnrolledCourse,
  type OnboardingCourse,
} from "@/lib/api";
import { useActiveSemester, distinctTerms, courseInTerm } from "@/lib/useActiveSemester";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { humanizeError } from "@/lib/errorMessage";
import { cn } from "@/lib/cn";

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
  const [activeSemester, setActiveSemester] = useActiveSemester();
  const terms = React.useMemo(() => distinctTerms(courses), [courses]);
  // Empty stored value = "All semesters" (the default): no term filter, and
  // every surface fetches unscoped. A term only scopes once the user picks it
  // here — the choice persists via the shared hook.
  const activeTerm = activeSemester;
  const [query, setQuery] = React.useState("");
  const [results, setResults] = React.useState<OnboardingCourse[]>([]);
  const [loading, setLoading] = React.useState(false);

  // Latest query wins (#769). Clearing the debounce timer only stops a search
  // that hasn't been SENT; one already in flight for an older query could
  // land after the newer one and replace its results (and its finally could
  // clear the newer search's spinner). The cleanup cancels it.
  const searchReq = useLatestRequest();
  React.useEffect(() => {
    if (!open) return;
    const run = searchReq.begin();
    const t = setTimeout(() => {
      setLoading(true);
      onboardingCoursesSearch(query)
        .then(r => { if (run.isCurrent()) setResults(r.courses ?? []); })
        .catch(() => { if (run.isCurrent()) setResults([]); })
        .finally(() => { if (run.isCurrent()) setLoading(false); });
    }, 200);
    return () => {
      clearTimeout(t);
      searchReq.cancel();
    };
  }, [query, open, searchReq]);

  const enrolledIds = React.useMemo(() => new Set(courses.map(c => c.course_id)), [courses]);
  const enrolledTermById = React.useMemo(() => {
    const m = new Map<string, string>();
    for (const c of courses) m.set(c.course_id, c.term);
    return m;
  }, [courses]);

  // Course id whose add request is in flight; disables the Add buttons so a
  // double-click can't race two enrollments for the same course.
  const [addingId, setAddingId] = React.useState<string | null>(null);

  const handleAdd = async (course: OnboardingCourse) => {
    if (addingId) return;
    setAddingId(course.id);
    try {
      const color = DEFAULT_COLORS[courses.length % DEFAULT_COLORS.length];
      // Enroll into the semester tab the user is viewing so the course lands
      // where they expect it. Empty activeTerm (no courses yet) → the backend
      // falls back to the current term.
      const res = await addCourse(userId, course.id, color, undefined, activeTerm || undefined);
      if (res.already_existed) {
        // The no-retake rule caught an enrollment this list didn't know about
        // (e.g. added from another tab/device). Nothing was created, so don't
        // claim success.
        toast.info(res.term ? `Already taken in ${res.term}` : "Already taken");
      } else {
        toast.success(`Added ${course.course_code || course.course_name}`);
      }
      await onChanged();
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't add that course. Try again."));
    } finally {
      setAddingId(null);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} labelledBy="manage-courses-title" width="620px" padding="0" zIndex={200} showCloseButton={false}>
      <div className="max-h-[80vh] overflow-hidden flex flex-col">
        <div className="flex justify-between items-center py-4 px-5 border-b border-b-border">
          <div id="manage-courses-title" className="h-serif text-[20px]">Courses & Semesters</div>
          <button className="btn btn--ghost btn--sm" onClick={onClose} aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>

        <div className="p-5 overflow-y-auto">
          <div className="label-micro mb-2">Semester</div>
          {terms.length === 0 ? (
            <div className="text-sm text-text-muted mb-4">
              No semesters yet — add a course below.
            </div>
          ) : (
            <div className="flex gap-1.5 flex-wrap mb-4">
              {/* "All semesters" is the default (empty stored value); clicking
                  it clears the stored term so every surface goes unscoped. */}
              <button
                onClick={() => setActiveSemester("")}
                className={cn("btn btn--sm", "border border-border", activeTerm === "" ? "bg-accent-soft" : "bg-bg-panel", activeTerm === "" ? "text-accent" : "text-text-dim")}
                aria-pressed={activeTerm === ""}
              >
                All semesters
              </button>
              {terms.map((t) => (
                <button
                  key={t}
                  onClick={() => setActiveSemester(t)}
                  className={cn("btn btn--sm", "border border-border", t === activeTerm ? "bg-accent-soft" : "bg-bg-panel", t === activeTerm ? "text-accent" : "text-text-dim")}
                  aria-pressed={t === activeTerm}
                >
                  {t}
                </button>
              ))}
            </div>
          )}

          <div className="label-micro mb-2">
            {activeTerm ? `Courses · ${activeTerm}` : "Your courses"}
          </div>
          <div className="flex flex-col gap-2 mb-5">
            {courses.filter((c) => courseInTerm(c, activeTerm)).length === 0 && (
              <div className="text-sm text-text-muted">
                No courses in this semester yet.
              </div>
            )}
            {courses
              .filter((c) => courseInTerm(c, activeTerm))
              .map((c) => (
                <EnrolledRow
                  key={c.course_id}
                  userId={userId}
                  course={c}
                  // Remove drops the enrollment for the tab being viewed (or,
                  // under "All semesters", the course's representative term)
                  // — never every term's, which wiped past gradebooks (#766).
                  dropTerm={activeTerm || c.term}
                  onChanged={onChanged}
                />
              ))}
          </div>

          <div className="label-micro mb-2">Add a course</div>
          <div className="relative mb-2.5">
            <input
              autoFocus
              aria-label="Search courses"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search by code or name (e.g. MATH 242)"
              className="w-full py-2 px-3 border border-border rounded-sm bg-bg-input text-md"
            />
          </div>
          {/* Fixed height: "Searching…" swapping in for the results must not
              resize the modal (it made the whole card jump as it opened). */}
          <div className="border border-border rounded-sm h-55 overflow-y-auto">
            {loading && <div className="p-3 text-sm text-text-muted">Searching…</div>}
            {!loading && results.length === 0 && (
              <div className="p-3 text-sm text-text-muted">No matches.</div>
            )}
            {!loading && results.map(c => {
              const enrolled = enrolledIds.has(c.id);
              return (
                <div
                  key={c.id}
                  className="flex items-center justify-between py-2 px-3 border-b border-b-border text-md"
                >
                  <div className="min-w-0">
                    <div className="font-medium">{c.course_code}</div>
                    <div className="text-xs text-text-muted">{c.course_name}</div>
                  </div>
                  <button
                    className={cn("btn btn--sm", enrolled ? "opacity-55" : "opacity-100", enrolled ? "bg-bg-subtle" : "")}
                    disabled={enrolled || addingId !== null}
                    onClick={() => handleAdd(c)}
                    title={enrolled ? "A course can only be taken once across semesters" : undefined}
                  >
                    {enrolled
                      ? `Already taken${enrolledTermById.get(c.id) ? ` · ${enrolledTermById.get(c.id)}` : ""}`
                      : addingId === c.id
                        ? "Adding…"
                        : <><Icon name="plus" size={12} /> Add</>}
                  </button>
                </div>
              );
            })}
          </div>

          <div className="border-t border-t-border mt-5 pt-4">
            <button
              className="btn btn--sm opacity-50 cursor-not-allowed"
              disabled
              aria-disabled="true"
            >
              <Icon name="sparkle" size={12} /> Personal learning
            </button>
            <div className="text-xs text-text-muted mt-1.5">
              Coming soon
            </div>
          </div>
        </div>
      </div>
    </Dialog>
  );
}

function EnrolledRow({
  userId, course, dropTerm, onChanged,
}: {
  userId: string;
  course: EnrolledCourse;
  dropTerm?: string;
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
      toast.error(humanizeError(err, "Couldn't save that change. Try again."));
    }
  };

  const doDelete = async () => {
    try {
      await deleteCourse(userId, course.course_id, dropTerm || undefined);
      toast.success(`Removed ${course.course_code || course.course_name}`);
      await onChanged();
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't save that change. Try again."));
    }
  };

  const del = useConfirm(doDelete);

  return (
    <div
      className="flex items-center gap-2.5 py-2 px-2.5 border border-border rounded-sm bg-bg-subtle"
    >
      <div className="relative w-6 h-6 shrink-0">
        <input
          type="color"
          value={valid ? color : "#888888"}
          onChange={e => { setColor(e.target.value); setDirty(true); }}
          onBlur={saveColor}
          aria-label={`Color for ${course.course_name}`}
          className="absolute inset-0 opacity-0 cursor-pointer w-full h-full"
        />
        <span
          aria-hidden
          className="block w-6 h-6 rounded-[50%] border border-border-strong" style={{ background: valid ? color : "var(--bg-soft)" }}
        />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-md font-medium">{course.course_code || course.course_name}</div>
        <div className="text-xs text-text-muted">
          {course.course_code ? course.course_name : ""} · {course.node_count} concepts
        </div>
      </div>
      <input
        value={color}
        onChange={e => { setColor(e.target.value); setDirty(true); }}
        onBlur={saveColor}
        onKeyDown={e => { if (e.key === "Enter") saveColor(); }}
        className={cn("mono w-21 py-1 px-1.5 rounded-xs bg-bg-input text-xs", valid ? "border border-border" : "border border-err")}
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
