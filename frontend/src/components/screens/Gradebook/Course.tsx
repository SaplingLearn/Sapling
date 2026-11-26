"use client";
import React from "react";
import { createPortal } from "react-dom";
import { useOverlayBehaviour } from "@/components/Dialog";
import Link from "next/link";
import { TopBar } from "@/components/TopBar";
import { FullHeightScreen } from "@/components/FullHeightScreen";
import { useUser } from "@/context/UserContext";
import { useToast } from "@/components/ToastProvider";
import {
  getGradebookCourse,
  bulkUpdateCategories,
  deleteCategory,
  createGradedAssignment,
  updateGradedAssignment,
  deleteGradedAssignment,
  setLetterScale,
  getGradescopeStatus,
  listGradescopeLinks,
  syncGradescopeCourse,
  setCurveSettings,
} from "@/lib/api";
import { humanizeError, statusOf } from "@/lib/errorMessage";
import { applyCurveToAssignment, hasCurveData } from "@/components/Gradebook/curveUtils";
import { EditWeightsModal } from "@/components/Gradebook/EditWeightsModal";
import { AssignmentList } from "@/components/Gradebook/AssignmentList";
import { AssignmentModal, type AssignmentDraft } from "@/components/Gradebook/AssignmentModal";
import { LetterScaleEditor } from "@/components/Gradebook/LetterScaleEditor";
import { GradescopeSyncModal } from "@/components/Gradebook/GradescopeSyncModal";
import { gradescopeConnectionState, needsGradescopeSignIn } from "@/components/Gradebook/gradescopeState";
import { percentColor } from "@/components/Gradebook/CourseCard";
import { projectGrade, droppedAssignmentIds } from "@/components/Gradebook/GradeProjector";
import { GradePredictorPanel } from "@/components/Gradebook/GradePredictorPanel";
import { Button } from "@/components/ui";
import type {
  GradebookCourse,
  GradeCategory,
  GradedAssignment,
  LetterScaleTier,
} from "@/lib/types";
import { cn } from "@/lib/cn";

const DEFAULT_SCALE: LetterScaleTier[] = [
  { letter: "A",  min: 93 },
  { letter: "A-", min: 90 },
  { letter: "B+", min: 87 },
  { letter: "B",  min: 83 },
  { letter: "B-", min: 80 },
  { letter: "C+", min: 77 },
  { letter: "C",  min: 73 },
  { letter: "C-", min: 70 },
  { letter: "D+", min: 67 },
  { letter: "D",  min: 63 },
  { letter: "D-", min: 60 },
  { letter: "F",  min: 0  },
];

function compactLetterScale(
  scale: LetterScaleTier[] | null,
): { letter: string; min: number }[] {
  const base: LetterScaleTier[] =
    scale && scale.length > 0 ? scale : DEFAULT_SCALE;
  const sorted = [...base].sort((a, b) => b.min - a.min);
  const seen = new Set<string>();
  const out: { letter: string; min: number }[] = [];
  for (const tier of sorted) {
    const prefix = tier.letter.charAt(0).toUpperCase();
    if (!seen.has(prefix) && /^[A-DF]$/.test(prefix)) {
      seen.add(prefix);
      out.push({ letter: prefix, min: tier.min });
    }
  }
  if (!seen.has("F")) out.push({ letter: "F", min: 0 });
  return out;
}

function tierFor(scale: LetterScaleTier[], pct: number): string | undefined {
  // 4dp to match backend letter_for() — a 1dp round would push 89.95 to 90.0 (A-)
  // while the server keeps it B+.
  const rounded = Math.round(pct * 1e4) / 1e4;
  return [...scale].sort((a, b) => b.min - a.min).find((t) => rounded >= t.min)?.letter;
}

function majorTicks(scale: LetterScaleTier[]): { letter: string; min: number }[] {
  const seen = new Set<string>();
  const out: { letter: string; min: number }[] = [];
  for (const t of [...scale].sort((a, b) => b.min - a.min)) {
    const prefix = t.letter.charAt(0).toUpperCase();
    if (!seen.has(prefix) && /^[A-D]$/.test(prefix)) {
      seen.add(prefix);
      out.push({ letter: prefix, min: t.min });
    }
  }
  return out.sort((a, b) => a.min - b.min);
}

interface Props {
  courseId: string;
}

// /gradebook/<id>?semester=<label> — the landing's cards carry the selected
// term so a course enrolled in several terms resolves to that term's
// enrollment instead of 404ing off the current one (#139). Read straight off
// location (useSearchParams() would need a Suspense boundary in the route
// shell, which this screen doesn't own), and read it at CALL time — every
// fetch AND every course-keyed mutation below must see the URL the user is
// actually on, not a mount-frozen copy. Writes that drop the term would
// silently land on the CURRENT term's enrollment (#468 review).
function currentSemesterParam(): string | undefined {
  if (typeof window === "undefined") return undefined;
  return new URLSearchParams(window.location.search).get("semester") || undefined;
}

// Exported for Course.curveModal.test.tsx (#166 failure-surfacing contract);
// only GradebookCourseScreen below renders it in the app.
export function CurveSettingsModal({
  open,
  course,
  onClose,
  onSave,
}: {
  open: boolean;
  course: import("@/lib/types").GradebookCourse;
  onClose: () => void;
  onSave: (settings: {
    curve_avg_target: number | null;
    curve_sd_delta: number | null;
  }) => Promise<void>;
}) {
  const toast = useToast();
  const [avgTarget, setAvgTarget] = React.useState<string>(
    course.curve_avg_target != null ? (course.curve_avg_target * 100).toFixed(0) : "83"
  );
  const [sdDelta, setSdDelta] = React.useState<string>(
    course.curve_sd_delta != null ? (course.curve_sd_delta * 100).toFixed(0) : "10"
  );
  const [saving, setSaving] = React.useState(false);
  // Dialog's modal engine (scroll lock, focus, Escape, Tab trap) with this
  // panel's own chrome.
  const { mounted, panelRef, onKeyDown } = useOverlayBehaviour({ open, onClose });
  React.useEffect(() => {
    if (!open) return;
    setAvgTarget(course.curve_avg_target != null ? (course.curve_avg_target * 100).toFixed(0) : "83");
    setSdDelta(course.curve_sd_delta != null ? (course.curve_sd_delta * 100).toFixed(0) : "10");
  }, [open, course]);
  if (!mounted || !open) return null;

  const toFloat = (s: string): number | null =>
    s.trim() === "" ? null : Number(s) / 100;

  return createPortal(
    <div
      className="fixed inset-0 bg-[rgba(0,0,0,0.4)] flex items-center justify-center z-100"
      onClick={onClose}
      onKeyDown={onKeyDown}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="curve-settings-title"
        onClick={(e) => e.stopPropagation()}
        className="bg-bg rounded-[12px] p-6 min-w-100 max-w-120 outline-none"
      >
        <h3 id="curve-settings-title" className="mt-0 mx-0 mb-1">Bell Curve Settings</h3>
        <p className="mt-0 mx-0 mb-4 text-sm text-text-dim leading-[1.5]">
          The curve policy comes from your syllabus. The class average maps to a target
          grade; each standard deviation above or below shifts the grade by a fixed amount.
        </p>
        <div className="grid gap-2.5 mb-4">
          <p className="m-0 text-md text-text-muted font-sans">
            Course Policy (from syllabus)
          </p>
          <div className="flex gap-2">
            <label className="flex-1">
              Average maps to (%)
              <input type="number" min={0} max={100} value={avgTarget}
                onChange={(e) => setAvgTarget(e.target.value)}
                className="w-full p-1.5 border border-border rounded-sm" />
            </label>
            <label className="flex-1">
              Grade per SD (%)
              <input type="number" min={0} max={50} value={sdDelta}
                onChange={(e) => setSdDelta(e.target.value)}
                className="w-full p-1.5 border border-border rounded-sm" />
            </label>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5 pt-3 border-t border-t-border">
          <button type="button" onClick={onClose}>Cancel</button>
          <Button
            variant="primary"
            size="sm"
            disabled={saving}
            // On failure the modal stays open (no onClose) so the user can
            // see the toast and retry — closing would look like success.
            onClick={async () => {
              setSaving(true);
              try {
                await onSave({
                  curve_avg_target: toFloat(avgTarget),
                  curve_sd_delta: toFloat(sdDelta),
                });
                onClose();
              } catch (err) {
                toast.error(humanizeError(err, "Couldn't save curve settings. Try again."));
              } finally { setSaving(false); }
            }}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export function GradebookCourseScreen({ courseId }: Props) {
  const { userId, userReady } = useUser();
  const toast = useToast();

  const [data, setData] = React.useState<GradebookCourse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [fetchError, setFetchError] = React.useState<string | null>(null);

  const skeletonCount = React.useMemo<number>(() => {
    if (typeof window === "undefined") return 4;
    const n = window.sessionStorage.getItem(`gb-cats-${courseId}`);
    const parsed = n ? parseInt(n, 10) : NaN;
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 4;
  }, [courseId]);
  React.useEffect(() => {
    if (data?.categories && typeof window !== "undefined") {
      window.sessionStorage.setItem(`gb-cats-${courseId}`, String(data.categories.length));
    }
  }, [data, courseId]);
  const [editWeights, setEditWeights] = React.useState(false);
  const [editScale, setEditScale] = React.useState(false);
  const [syncOpen, setSyncOpen] = React.useState(false);
  const [highlightedCategory, setHighlightedCategory] = React.useState<string | null>(null);
  const [gscope, setGscope] = React.useState<{
    ready: boolean;
    lastSyncedAt: string | null;
  }>({ ready: false, lastSyncedAt: null });
  const [gscopeBusy, setGscopeBusy] = React.useState(false);
  const [assignModal, setAssignModal] = React.useState<{
    open: boolean;
    initial: import("@/lib/types").GradedAssignment | null;
  }>({ open: false, initial: null });
  const [predictorOpen, setPredictorOpen] = React.useState(false);
  const [predictorCurveEnabled, setPredictorCurveEnabled] = React.useState(false);
  const [hypotheticals, setHypotheticals] = React.useState<
    Map<string, { earned: number; possible: number; curveClassMean: number | null; curveClassSd: number | null }>
  >(new Map());
  const [curveSettingsOpen, setCurveSettingsOpen] = React.useState(false);

  // Latest-wins (#770): every mutation below ends in refresh(), so two quick
  // edits put two course reads in flight, and the older one could land last
  // and paint the pre-edit grade back. Only the newest read may touch state.
  const refreshSeq = React.useRef(0);
  const refresh = React.useCallback(async () => {
    if (!userId) return;
    const seq = ++refreshSeq.current;
    setFetchError(null);
    try {
      const fresh = await getGradebookCourse(userId, courseId, currentSemesterParam());
      if (seq !== refreshSeq.current) return;
      setData(fresh);
    } catch (err: unknown) {
      if (seq !== refreshSeq.current) return;
      const errMsg = humanizeError(err, "Unknown error");
      setFetchError(errMsg);
      toast.error(`Couldn't load course: ${errMsg}`);
    } finally {
      // Whichever read is newest ends the initial load, so a superseded
      // loadInitial can neither drop the skeleton early nor leave it stuck.
      if (seq === refreshSeq.current) setLoading(false);
    }
  }, [userId, courseId, toast]);

  const loadInitial = React.useCallback(async () => {
    setLoading(true);
    await refresh();
  }, [refresh]);

  // A different course (or account) starts from nothing: the previous
  // course's grades must not stay on screen, or be edited, under this URL.
  React.useEffect(() => {
    setData(null);
  }, [userId, courseId]);

  React.useEffect(() => {
    void loadInitial();
    // Cancel: a read still in flight for the previous course/account must
    // not land on this one. (The counter ref, not a DOM ref: bumping its
    // live value at cleanup time is exactly the intent.)
    const seq = refreshSeq;
    return () => { seq.current++; };
  }, [loadInitial]);

  // Without ?semester= the term is whatever the course load resolved. Asking
  // before then would list every term's link, and that unscoped answer could
  // land after the scoped one and mark this term as linked.
  const courseLoaded = data !== null;
  const gscopeSeq = React.useRef(0);
  const refreshGscope = React.useCallback(async () => {
    if (!userId) return;
    if (!currentSemesterParam() && !courseLoaded) return;
    // Latest-wins, like refresh(): an older status answer must not mark the
    // course linked (or unlinked) over a newer one.
    const seq = ++gscopeSeq.current;
    try {
      const status = await getGradescopeStatus(userId);
      if (seq !== gscopeSeq.current) return;
      // Only a working connection syncs in one click. Disconnected (links
      // survive a disconnect) or rejected credentials open the dialog instead.
      if (gradescopeConnectionState(status) !== "connected") {
        setGscope({ ready: false, lastSyncedAt: null });
        return;
      }
      const res = await listGradescopeLinks(userId, currentSemesterParam() ?? data?.semester);
      if (seq !== gscopeSeq.current) return;
      const myLink = res.links.find((l) => l.sapling_course_id === courseId);
      setGscope({
        ready: !!myLink,
        lastSyncedAt: myLink?.last_synced_at ?? null,
      });
    } catch {
      if (seq !== gscopeSeq.current) return;
      setGscope({ ready: false, lastSyncedAt: null });
    }
  }, [userId, courseId, courseLoaded, data?.semester]);

  React.useEffect(() => {
    refreshGscope();
  }, [refreshGscope]);

  const directSyncGradescope = React.useCallback(async () => {
    if (!userId) return;
    setGscopeBusy(true);
    try {
      const res = await syncGradescopeCourse(userId, courseId, currentSemesterParam() ?? data?.semester);
      const summary =
        res.failed > 0
          ? `Synced: ${res.inserted} added · ${res.updated} updated · ${res.failed} failed`
          : `Synced: ${res.inserted} added · ${res.updated} updated`;
      if (res.failed > 0) toast.error(summary);
      else toast.success(summary);
      await Promise.all([refresh(), refreshGscope()]);
    } catch (err: unknown) {
      const msg = humanizeError(err, "Sync failed");
      toast.error(msg);
      // #770: only the typed Gradescope rejection means "reconnect Gradescope";
      // 400 = no course linked, 409 = ambiguous links — both fixed in the
      // dialog. A 401 is Sapling's own session: the toast says so, and the
      // Gradescope dialog is the wrong remedy for it.
      const status = statusOf(err);
      if (needsGradescopeSignIn(err) || status === 400 || status === 409) {
        setSyncOpen(true);
        await refreshGscope();
      }
    } finally {
      setGscopeBusy(false);
    }
  }, [userId, courseId, data?.semester, refresh, refreshGscope, toast]);

  const onClickSyncButton = React.useCallback(() => {
    if (gscope.ready && !gscopeBusy) directSyncGradescope();
    else setSyncOpen(true);
  }, [gscope.ready, gscopeBusy, directSyncGradescope]);

  const onEditGrade = React.useCallback(
    async (id: string, points: number | null) => {
      if (!userId || !data) return;
      // Clear any hypothetical for this assignment now that it has a real score
      setHypotheticals((h) => {
        if (!h.has(id)) return h;
        const next = new Map(h);
        next.delete(id);
        return next;
      });
      // Per-field rollback (#770): a whole-object snapshot restored on failure
      // also wiped every other edit made while this save was in flight.
      // Remember only this assignment's previous score, and undo only this
      // field, and only if nothing newer has been written to it since.
      const before = data.assignments.find((a) => a.id === id)?.points_earned ?? null;
      const withPoints = (value: number | null, onlyIf?: number | null) =>
        (cur: GradebookCourse | null) => cur && {
          ...cur,
          assignments: cur.assignments.map((a) =>
            a.id === id && (onlyIf === undefined || a.points_earned === onlyIf)
              ? { ...a, points_earned: value }
              : a,
          ),
        };
      setData(withPoints(points));
      try {
        await updateGradedAssignment(userId, id, { points_earned: points });
        await refresh();
      } catch (err: unknown) {
        setData(withPoints(before, points));
        toast.error(`Couldn't save: ${humanizeError(err, "Try again.")}`);
      }
    },
    [userId, data, refresh, toast],
  );

  const focusCategory = React.useCallback((categoryId: string) => {
    const el = document.getElementById(`category-${categoryId}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    setHighlightedCategory(categoryId);
    window.setTimeout(() => setHighlightedCategory(null), 1600);
  }, []);

  const ungradedAssignments = React.useMemo(
    () => (data?.assignments ?? []).filter((a) => a.points_earned === null),
    [data],
  );

  const augmentedAssignments = React.useMemo(() => {
    if (!predictorOpen || !data) return data?.assignments ?? [];
    const curvePolicy = predictorCurveEnabled && data.curve_mode === "curved"
      && data.curve_avg_target != null && data.curve_sd_delta != null ? {
      curve_avg_target: data.curve_avg_target,
      curve_sd_delta: data.curve_sd_delta,
    } : null;
    return data.assignments.map((a) => {
      const hyp = hypotheticals.get(a.id);
      let result = a;
      if (a.points_earned === null && hyp) {
        result = {
          ...a,
          points_earned: hyp.earned,
          points_possible: hyp.possible > 0 ? hyp.possible : a.points_possible,
          // Predictor override takes priority over stored assignment class stats
          curve_class_mean: hyp.curveClassMean !== null ? hyp.curveClassMean : a.curve_class_mean,
          curve_class_sd: hyp.curveClassSd !== null ? hyp.curveClassSd : a.curve_class_sd,
        };
      }
      if (curvePolicy) result = applyCurveToAssignment(result, curvePolicy);
      return result;
    });
  }, [predictorOpen, data, hypotheticals, predictorCurveEnabled]);

  const predictedProjection = React.useMemo(
    () =>
      predictorOpen && data
        ? projectGrade(data.categories, augmentedAssignments)
        : null,
    [predictorOpen, data, augmentedAssignments],
  );

  const predictedCurvedPercent = React.useMemo(() => {
    if (!predictedProjection || !data) return null;
    const raw = predictedProjection.current;
    return raw;
  }, [predictedProjection, data]);

  const predictedLetter = React.useMemo(() => {
    if (predictedCurvedPercent == null || !data) return null;
    const scale =
      data.letter_scale && data.letter_scale.length > 0
        ? data.letter_scale
        : DEFAULT_SCALE;
    const rounded = Math.round(predictedCurvedPercent * 1e4) / 1e4;
    return (
      [...scale].sort((a, b) => b.min - a.min).find((t) => rounded >= t.min)
        ?.letter ?? null
    );
  }, [predictedCurvedPercent, data]);

  const handleHypotheticalChange = React.useCallback(
    (id: string, score: { earned: number; possible: number; curveClassMean: number | null; curveClassSd: number | null }) => {
      setHypotheticals((prev) => {
        const next = new Map(prev);
        next.set(id, score);
        return next;
      });
    },
    [],
  );

  const handleResetPredictor = React.useCallback(() => {
    setHypotheticals(new Map());
  }, []);

  const handleTogglePredictor = React.useCallback(() => {
    setPredictorOpen((prev) => {
      if (prev) setHypotheticals(new Map()); // reset hypotheticals on close
      return !prev;
    });
  }, []);

  const hasCurve = React.useMemo(
    () => (data?.assignments ?? []).some(hasCurveData),
    [data],
  );

  const curvedAssignments = React.useMemo(() => {
    if (!data || data.curve_mode !== "curved") return data?.assignments ?? [];
    if (data.curve_avg_target === null || data.curve_sd_delta === null) return data.assignments;
    const policy = {
      curve_avg_target: data.curve_avg_target,
      curve_sd_delta: data.curve_sd_delta,
    };
    return data.assignments.map((a) => applyCurveToAssignment(a, policy));
  }, [data]);

  const handleToggleCurveMode = React.useCallback(async () => {
    if (!data || !userId) return;
    const oldMode = data.curve_mode;
    const newMode = oldMode === "curved" ? "raw" : "curved";
    setData((prev) => prev ? { ...prev, curve_mode: newMode } : prev);
    try {
      await setCurveSettings(
        userId,
        courseId,
        { curve_mode: newMode },
        currentSemesterParam(),
      );
      await refresh(); // Server recomputes data.percent with the new curve_mode
    } catch (err: unknown) {
      // Undo only this toggle, and only if nothing has moved the mode since;
      // and say so — a silent flip back read as the click not registering.
      setData((prev) => prev && prev.curve_mode === newMode ? { ...prev, curve_mode: oldMode } : prev);
      toast.error(`Couldn't switch to ${newMode} grades: ${humanizeError(err, "Try again.")}`);
    }
  }, [data, userId, courseId, refresh, toast]);

  const handleSaveCurveSettings = React.useCallback(
    async (settings: {
      curve_avg_target: number | null;
      curve_sd_delta: number | null;
    }) => {
      if (!data || !userId) return;
      await setCurveSettings(
        userId,
        courseId,
        { curve_mode: data.curve_mode, ...settings },
        currentSemesterParam(),
      );
      await refresh(); // Recompute server grade with new curve policy
    },
    [data, userId, courseId, refresh],
  );

  React.useEffect(() => {
    if (!data) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        return;
      }
      if (!/^[1-9]$/.test(e.key)) return;
      const sorted = [...data.categories].sort((a, b) => a.sort_order - b.sort_order);
      const idx = parseInt(e.key, 10) - 1;
      const cat = sorted[idx];
      if (cat) {
        focusCategory(cat.id);
        e.preventDefault();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [data, focusCategory]);

  if (!userReady || !userId) return null;

  return (
    <FullHeightScreen>
      <TopBar
        breadcrumb={
          <Link href="/gradebook" className="text-text-dim no-underline">
            ← Gradebook
          </Link>
        }
        actions={
          <div className="flex gap-2 items-center">
            {data && (
              <>
                {hasCurve && (
                  <div className="flex bg-bg-subtle rounded-[20px] p-0.5">
                    {(["raw", "curved"] as const).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        onClick={data.curve_mode !== mode ? handleToggleCurveMode : undefined}
                        className={cn("py-1 px-3 rounded-[18px] text-xs font-medium border-0 font-sans", data.curve_mode === mode ? "bg-accent" : "bg-transparent", data.curve_mode === mode ? "text-accent-fg" : "text-text-dim", data.curve_mode !== mode ? "cursor-pointer" : "cursor-default")}
                      >
                        {mode === "raw" ? "Raw" : "Curved"}
                      </button>
                    ))}
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => setCurveSettingsOpen(true)}
                  className="btn py-1 px-3 text-sm flex items-center gap-[5px]"
                  title="Bell curve policy"
                >
                  <span>⚙</span>
                  <span>Curve</span>
                </button>
              </>
            )}
            <button
              type="button"
              onClick={() => setEditScale(true)}
              className="btn py-1 px-3 text-sm"
            >
              Letter Scale
            </button>
          </div>
        }
      />
      <main
        className="p-(--pad-xl) relative flex-[1_0_auto]"
      >
        <div
          className="relative z-1 max-w-310 my-0 mx-auto"
        >
          {loading && !data ? (
            <CoursePageSkeleton segmentCount={skeletonCount} />
          ) : fetchError && !data ? (
            <ErrorBanner message={fetchError} onRetry={loadInitial} />
          ) : data ? (
            <>
              <Masthead data={data} />
              <GradeCompositionBar
                categories={data.categories}
                assignments={
                  predictorOpen
                    ? augmentedAssignments
                    : data.curve_mode === "curved"
                      ? curvedAssignments
                      : data.assignments
                }
                letterScale={data.letter_scale}
                currentPercent={
                  predictorOpen
                    ? (predictedProjection?.current ?? null)
                    : null
                }
                onEditWeights={() => setEditWeights(true)}
                onSegmentClick={focusCategory}
                isPredicted={predictorOpen}
              />
              <GradePredictorPanel
                open={predictorOpen}
                onToggle={handleTogglePredictor}
                ungradedAssignments={ungradedAssignments}
                categories={data.categories}
                hypotheticals={hypotheticals}
                onHypotheticalChange={handleHypotheticalChange}
                onReset={handleResetPredictor}
                predictedPercent={predictedCurvedPercent}
                predictedLetter={predictedLetter}
                isCurved={data.curve_mode === "curved"}
                predictorCurveEnabled={predictorCurveEnabled}
                onTogglePredictorCurve={() => setPredictorCurveEnabled((v) => !v)}
              />
              {/* AssignmentList always receives real grades — the predictor is display-only */}
              <AssignmentList
                assignments={data.assignments}
                curvedAssignments={data.curve_mode === "curved" ? curvedAssignments : undefined}
                categories={data.categories}
                droppedIds={droppedAssignmentIds(data.categories, data.assignments)}
                highlightedCategory={highlightedCategory}
                onAdd={() => setAssignModal({ open: true, initial: null })}
                onEditFull={(a) => setAssignModal({ open: true, initial: a })}
                onEditGrade={onEditGrade}
                onSyncGradescope={onClickSyncButton}
                onGradescopeSettings={
                  gscope.ready ? () => setSyncOpen(true) : undefined
                }
                gradescopeReady={gscope.ready}
                gradescopeBusy={gscopeBusy}
                gradescopeLastSyncedAt={gscope.lastSyncedAt}
              />
            </>
          ) : null}
        </div>
      </main>

      {data && (
        <>
          {/* The onSave/onDelete callbacks below deliberately don't catch:
              each modal catches, toasts, and stays open on failure (#166). */}
          <EditWeightsModal
            open={editWeights}
            initial={data.categories}
            onClose={() => setEditWeights(false)}
            onSave={async (drafts) => {
              const draftIds = new Set(drafts.map((d) => d.id).filter(Boolean) as string[]);
              for (const c of data.categories) {
                // deleteCategory is id-keyed (ownership check server-side) —
                // no term needed; the course-keyed bulk PATCH below is.
                if (!draftIds.has(c.id)) await deleteCategory(userId, c.id);
              }
              await bulkUpdateCategories(userId, courseId, drafts, currentSemesterParam());
              await refresh();
            }}
          />

          <AssignmentModal
            open={assignModal.open}
            initial={assignModal.initial}
            categories={data.categories}
            onClose={() => setAssignModal({ open: false, initial: null })}
            onSave={async (draft: AssignmentDraft) => {
              if (assignModal.initial) {
                // Id-keyed — the existing assignment already pins its enrollment.
                await updateGradedAssignment(userId, assignModal.initial.id, draft);
              } else {
                await createGradedAssignment(userId, courseId, draft, currentSemesterParam());
              }
              await refresh();
            }}
            onDelete={
              assignModal.initial
                ? async () => {
                    await deleteGradedAssignment(userId, assignModal.initial!.id);
                    await refresh();
                  }
                : null
            }
          />

          <LetterScaleEditor
            open={editScale}
            initial={data.letter_scale}
            onClose={() => setEditScale(false)}
            onSave={async (scale) => {
              await setLetterScale(userId, courseId, scale, currentSemesterParam());
              await refresh();
            }}
          />

          <GradescopeSyncModal
            open={syncOpen}
            userId={userId}
            saplingCourseId={courseId}
            semester={data.semester}
            saplingCourseLabel={`${data.course_code} · ${data.course_name}`}
            onClose={() => {
              setSyncOpen(false);
              refreshGscope();
            }}
            onSynced={() => {
              refresh();
              refreshGscope();
            }}
          />

          <CurveSettingsModal
            open={curveSettingsOpen}
            course={data}
            onClose={() => setCurveSettingsOpen(false)}
            onSave={handleSaveCurveSettings}
          />
        </>
      )}
    </FullHeightScreen>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Masthead — single-row identity strip. Code + semester kicker, course
// name in a smaller serif, letter+percent at the right. Hovering the
// letter cluster reveals the full scale; we don't burn vertical space on
// it since it's reference info, not a hero metric.
// ───────────────────────────────────────────────────────────────────────────
function Masthead({ data }: { data: GradebookCourse }) {
  const isEmpty = data.percent === null;
  const scale = compactLetterScale(data.letter_scale);
  const scaleText = scale
    .map((t, i) => {
      const isF = t.letter === "F";
      const prevMin = i > 0 ? scale[i - 1].min : null;
      return `${t.letter} ${isF ? `<${prevMin ?? 60}` : `${t.min}+`}`;
    })
    .join(" · ");
  const letterColor = percentColor(data.percent);
  return (
    <header
      className="flex items-end justify-between gap-8 mb-8 pb-5 border-b border-b-border"
    >
      <div className="min-w-0">
        <div
          className="mono text-md text-text-muted mb-2"
        >
          {data.course_code}
          {data.semester ? ` · ${data.semester}` : ""}
        </div>
        <h1
          className="font-display font-medium text-[length:clamp(26px,_3vw,_38px)] leading-[1.08] tracking-[-0.02em] text-text m-0"
        >
          {data.course_name}
        </h1>
      </div>
      <div
        title={`Letter scale: ${scaleText}`}
        className="flex items-baseline gap-2.5 shrink-0 cursor-help"
      >
        <span
          className={cn("font-display font-medium text-[42px] leading-none tracking-[-0.03em]", isEmpty ? "italic" : "not-italic", isEmpty ? "opacity-50" : "opacity-100")} style={{ color: letterColor }}
        >
          {isEmpty ? "—" : (data.letter ?? "—")}
        </span>
        <span
          className={cn("mono", "text-[15px] font-semibold tracking-[-0.02em]", isEmpty ? "opacity-50" : "opacity-85")}
          style={{ color: letterColor }}
        >
          {data.percent === null ? "—" : `${data.percent.toFixed(1)}%`}
        </span>
      </div>
    </header>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// GradeCompositionBar — full-width hero visualization. The bar's total
// span = 100% of the final grade. Each category occupies a slot whose
// width = its weight share. Inside each slot, three sub-segments encode:
//
//   solid green   — earned contribution (locked-in points toward final)
//   faded green   — lost contribution (graded, but didn't score)
//   diagonal hatch— remaining potential (still up for grabs)
//
// Letter-cutoff ticks overlay the bar at fixed scale positions (60/70/
// 80/90). A "now" pin marks current percent. Hovering any sub-segment
// pops a cursor-following tooltip with numerical detail.
// ───────────────────────────────────────────────────────────────────────────
type TipKind = "earned" | "lost" | "remaining" | "empty";
interface TipState {
  kind: TipKind;
  category: GradeCategory;
  pts: CategoryPts | null;
  contribution: number; // weight × fraction = % of final
  x: number;
  y: number;
}

function GradeCompositionBar({
  categories,
  assignments,
  letterScale,
  currentPercent,
  onEditWeights,
  onSegmentClick,
  isPredicted = false,
}: {
  categories: GradeCategory[];
  assignments: GradedAssignment[];
  letterScale: LetterScaleTier[] | null;
  currentPercent: number | null;
  onEditWeights: () => void;
  onSegmentClick: (categoryId: string) => void;
  isPredicted?: boolean;
}) {
  const sorted = React.useMemo(
    () => [...categories].sort((a, b) => a.sort_order - b.sort_order),
    [categories],
  );

  // For the bar only: put categories with earned points first (left), fully
  // ungraded last (right), so solid segments cluster on the left and hatched
  // segments cluster on the right — matching the grade-projector visual.
  const barSorted = React.useMemo(() => {
    return [...sorted].sort((a, b) => {
      const ptsA = categoryPoints(a.id, assignments, a.drop_lowest ?? 0);
      const ptsB = categoryPoints(b.id, assignments, b.drop_lowest ?? 0);
      const earnedA = ptsA ? ptsA.earned : 0;
      const earnedB = ptsB ? ptsB.earned : 0;
      // Categories with any earned points come before fully-ungraded ones.
      if ((earnedA > 0) !== (earnedB > 0)) return earnedA > 0 ? -1 : 1;
      // Among earned, sort by earned fraction descending.
      const totalA = ptsA && ptsA.total > 0 ? ptsA.total : 1;
      const totalB = ptsB && ptsB.total > 0 ? ptsB.total : 1;
      return earnedB / totalB - earnedA / totalA;
    });
  }, [sorted, assignments]);
  const totalWeight = sorted.reduce((s, c) => s + c.weight, 0);
  const scale = letterScale && letterScale.length > 0 ? letterScale : DEFAULT_SCALE;
  const ticks = majorTicks(scale);
  const projection = projectGrade(sorted, assignments);
  const current = currentPercent ?? projection?.current ?? null;
  const currentTier = current !== null ? tierFor(scale, current) : undefined;

  const [tip, setTip] = React.useState<TipState | null>(null);

  if (sorted.length === 0) {
    return (
      <section
        className="mb-10 py-7 px-6 rounded-md bg-bg-panel border border-border"
      >
        <SectionHead label="Composition" onEdit={onEditWeights} />
        <div
          className="font-serif text-text-dim text-[15px] leading-[1.55] mt-2"
        >
          No categories yet. Upload a syllabus or add them by hand to break
          your grade into pieces.
        </div>
      </section>
    );
  }

  return (
    <section className="mb-11">
      <SectionHead
        label="Composition"
        onEdit={onEditWeights}
        meta={
          <>
            {isPredicted && (
              <div className="chip chip--accent">
                Predicted
              </div>
            )}
            {current !== null && (
              <CompositionStatus
                current={current}
                currentTier={currentTier}
                projection={projection}
                scale={scale}
                isPredicted={isPredicted}
              />
            )}
          </>
        }
      />

      {/* Letter-tick scale above the bar */}
      <div className="relative h-6 mt-4.5 mb-2">
        {ticks.map(({ letter, min }) => (
          <div
            key={letter}
            className="absolute top-0 [transform:translateX(-50%)] text-center pointer-events-none" style={{ left: `${min}%` }}
          >
            <div
              className="mono text-2xs font-bold text-text-dim leading-none tracking-[-0.01em]"
            >
              {letter}
            </div>
            <div
              className="mono text-[9px] text-text-muted leading-[1.2] mt-0.5"
            >
              {min}
            </div>
          </div>
        ))}
      </div>

      {/* The composition bar itself */}
      <div
        className="relative w-full"
        onMouseLeave={() => setTip(null)}
      >
        <div
          className={cn("flex h-11.5 w-full bg-bg-subtle rounded-md overflow-hidden", isPredicted ? "border-[1.5px] border-dashed border-accent-border" : "border border-border")}
        >
          {barSorted.map((c, i) => {
            const pts = categoryPoints(c.id, assignments, c.drop_lowest ?? 0);
            const denom = pts && pts.total > 0 ? pts.total : 1;
            const earned = pts ? pts.earned : 0;
            const lost = pts ? pts.lost : 0;
            const remaining = pts ? pts.remaining : 1; // empty cat = all hatched
            const earnedFrac = earned / denom;
            const lostFrac = lost / denom;
            const remainingFrac = remaining / denom;
            const earnedPctOfSlot = earnedFrac * 100;
            const lostPctOfSlot = lostFrac * 100;
            const remainingPctOfSlot = remainingFrac * 100;
            const totalW = totalWeight > 0 ? totalWeight : 100;
            const contribEarned = (c.weight / totalW) * earnedFrac * 100;
            const contribLost = (c.weight / totalW) * lostFrac * 100;
            const contribRemaining = (c.weight / totalW) * remainingFrac * 100;
            const isEmptyCat = !pts || pts.total <= 0;

            const onMove =
              (kind: TipKind, contribution: number) =>
              (e: React.MouseEvent) => {
                setTip({
                  kind,
                  category: c,
                  pts,
                  contribution,
                  x: e.clientX,
                  y: e.clientY,
                });
              };

            return (
              <div
                key={c.id}
                onClick={() => onSegmentClick(c.id)}
                title={`Jump to ${c.name} assignments`}
                className={cn("flex cursor-pointer min-w-0", i < sorted.length - 1 ? "border-r border-r-bg-panel" : "border-r-0")} style={{ flex: `${c.weight} 0 0` }}
              >
                {isEmptyCat ? (
                  <div
                    className="w-full h-full [background-image:repeating-linear-gradient(135deg,_color-mix(in_oklch,_var(--sap-500),_transparent_70%)_0_6px,_transparent_6px_12px)]"
                    onMouseEnter={onMove("empty", contribRemaining)}
                    onMouseMove={onMove("empty", contribRemaining)}
                  />
                ) : (
                  <>
                    {earnedPctOfSlot > 0 && (
                      <div
                        className="h-full bg-sap-500" style={{ width: `${earnedPctOfSlot}%` }}
                        onMouseEnter={onMove("earned", contribEarned)}
                        onMouseMove={onMove("earned", contribEarned)}
                      />
                    )}
                    {lostPctOfSlot > 0 && (
                      <div
                        className="h-full bg-[color-mix(in_oklch,_var(--sap-500),_var(--bg-panel)_70%)]" style={{ width: `${lostPctOfSlot}%` }}
                        onMouseEnter={onMove("lost", contribLost)}
                        onMouseMove={onMove("lost", contribLost)}
                      />
                    )}
                    {remainingPctOfSlot > 0 && (
                      <div
                        className="h-full [background-image:repeating-linear-gradient(135deg,_color-mix(in_oklch,_var(--sap-500),_transparent_65%)_0_6px,_transparent_6px_12px)]" style={{ width: `${remainingPctOfSlot}%` }}
                        onMouseEnter={onMove("remaining", contribRemaining)}
                        onMouseMove={onMove("remaining", contribRemaining)}
                      />
                    )}
                  </>
                )}
              </div>
            );
          })}
        </div>

        {/* Letter-cutoff vertical guide lines crossing the bar */}
        {ticks.map(({ letter, min }) => (
          <div
            key={`tick-line-${letter}`}
            aria-hidden="true"
            className="absolute -top-1.5 -bottom-1.5 w-px bg-border-strong [transform:translateX(-0.5px)] pointer-events-none" style={{ left: `${min}%` }}
          />
        ))}

        {/* Now pin */}
        {current !== null && (
          <div
            aria-hidden="true"
            className="absolute -top-2 -bottom-2 w-[3px] bg-text rounded-[1px] [transform:translateX(-50%)] pointer-events-none [box-shadow:0_0_0_2px_var(--bg)]" style={{ left: `${current}%` }}
          />
        )}
      </div>

      {/* Category labels under their slots */}
      <div className="flex mt-3.5">
        {barSorted.map((c, i) => {
          const drop = c.drop_lowest ?? 0;
          return (
            <button
              key={c.id}
              type="button"
              onClick={() => onSegmentClick(c.id)}
              title={
                drop > 0
                  ? `${c.name}: drops ${drop} lowest. Click to jump to assignments.`
                  : `Jump to ${c.name} assignments`
              }
              className={cn("min-w-0 py-0 px-1.5 text-center bg-transparent border-0 cursor-pointer text-inherit", i === 0 ? "border-l-0" : "border-l border-l-border")} style={{ flex: `${c.weight} 0 0` }}
            >
              <div
                className="font-serif text-sm text-text overflow-hidden text-ellipsis whitespace-nowrap"
              >
                {c.name}
              </div>
              <div
                className="mono text-2xs text-text-muted mt-0.5 tracking-[-0.01em]"
              >
                {c.weight}%
                {drop > 0 && (
                  <span
                    className="ml-1.5 text-accent"
                    title={`Drops ${drop} lowest`}
                  >
                    · {drop} Drops
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {Math.abs(totalWeight - 100) > 0.01 && (
        <div
          className="mono text-2xs text-warn mt-3 tracking-[-0.01em]"
        >
          Weights sum to {totalWeight.toFixed(0)}%, not 100%. Final percent
          is normalized.
        </div>
      )}

      {/* Legend */}
      <div
        className="flex gap-5 mt-5.5 text-xs text-text-dim flex-wrap"
      >
        <LegendSwatch fill="var(--sap-500)" label="Earned" />
        <LegendSwatch
          fill="color-mix(in oklch, var(--sap-500), var(--bg-panel) 70%)"
          label="Lost"
        />
        <LegendSwatch
          fill="repeating-linear-gradient(135deg, color-mix(in oklch, var(--sap-500), transparent 65%) 0 4px, transparent 4px 8px)"
          label="Still Reachable"
          isImage
        />
      </div>

      {/* Cursor-following tooltip */}
      {tip && <CompositionTooltip tip={tip} />}
    </section>
  );
}

function SectionHead({
  label,
  onEdit,
  meta,
}: {
  label: string;
  onEdit: () => void;
  meta?: React.ReactNode;
}) {
  return (
    <div
      className="flex items-baseline justify-between gap-4 flex-wrap"
    >
      <div className="flex items-baseline gap-4 min-w-0">
        <span
          className="mono text-sm text-text-muted font-semibold"
        >
          {label}
        </span>
        {meta}
      </div>
      <button
        type="button"
        onClick={onEdit}
        className="font-sans text-sm font-medium text-text-dim [background:none] border-0 p-0 cursor-pointer underline [text-underline-offset:3px] decoration-border-strong"
      >
        Edit Weights
      </button>
    </div>
  );
}

function CompositionStatus({
  current,
  currentTier,
  projection,
  scale,
  isPredicted = false,
}: {
  current: number;
  currentTier: string | undefined;
  projection: ReturnType<typeof projectGrade>;
  scale: LetterScaleTier[];
  isPredicted?: boolean;
}) {
  const roundedCurrent = Math.round(current * 1e4) / 1e4;
  const nextUp = [...scale]
    .sort((a, b) => a.min - b.min)
    .find((t) => roundedCurrent < t.min);
  let action: string;
  if (!nextUp) action = "At the Top of the Scale";
  else if (projection && projection.floor >= nextUp.min)
    action = `${nextUp.letter} already guaranteed`;
  else if (projection && projection.ceiling < nextUp.min)
    action = `${nextUp.letter} out of reach by ${(nextUp.min - projection.ceiling).toFixed(1)}%`;
  else if (projection) {
    const span = projection.ceiling - projection.floor;
    const need = nextUp.min - projection.floor;
    const requiredAvg = span > 0 ? (need / span) * 100 : 0;
    action = `Need ${Math.max(0, Math.ceil(requiredAvg))}%+ avg on the rest for ${nextUp.letter}`;
  } else action = `${(nextUp.min - current).toFixed(1)} pts to ${nextUp.letter}`;

  return (
    <div className="flex items-baseline gap-2.5 min-w-0">
      <span
        className="font-display font-medium text-[20px] leading-none tracking-[-0.01em]" style={{ color: percentColor(current) }}
      >
        {current.toFixed(1)}%
      </span>
      {currentTier && (
        <span
          className="font-display text-base text-text-dim font-normal"
        >
          {currentTier}
        </span>
      )}
      <span
        className="text-sm text-text-dim ml-1 overflow-hidden text-ellipsis whitespace-nowrap"
      >
        · {action}
        {isPredicted && (
          <span className="text-text-muted ml-1">(Predicted)</span>
        )}
      </span>
    </div>
  );
}

function LegendSwatch({
  fill,
  label,
  isImage,
}: {
  fill: string;
  label: string;
  isImage?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="inline-block w-3.5 h-2.5 rounded-[2px]" style={{ ...(isImage ? { backgroundImage: fill } : { background: fill }) }}
      />
      {label}
    </span>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// CompositionTooltip — cursor-following hover card. Position is
// viewport-relative (clientX/Y), and flips to the cursor's left or above
// when it would otherwise overflow the right/bottom edges of the
// viewport. pointer-events: none so the tooltip can't capture its own
// mouseleave.
// ───────────────────────────────────────────────────────────────────────────
function CompositionTooltip({ tip }: { tip: TipState }) {
  const { kind, category, pts, contribution, x, y } = tip;
  const OFFSET = 14;
  const TIP_W = 280;
  const TIP_H_EST = 110;
  const vw = typeof window !== "undefined" ? window.innerWidth : 1200;
  const vh = typeof window !== "undefined" ? window.innerHeight : 800;
  const flipX = x + OFFSET + TIP_W > vw;
  const flipY = y + OFFSET + TIP_H_EST > vh;
  const left = flipX ? x - OFFSET - TIP_W : x + OFFSET;
  const top = flipY ? y - OFFSET - TIP_H_EST : y + OFFSET;

  const title = category.name;
  let body: React.ReactNode = null;
  if (kind === "earned" && pts) {
    body = (
      <>
        <Row label="Earned" value={`${pts.earned.toFixed(1)} of ${pts.total.toFixed(0)} pts`} />
        <Row label="Locked-in contribution" value={`${contribution.toFixed(2)}% of final`} />
        <Row label="Weight" value={`${category.weight}%`} muted />
      </>
    );
  } else if (kind === "lost" && pts) {
    body = (
      <>
        <Row label="Lost" value={`${pts.lost.toFixed(1)} pts on graded work`} />
        <Row label="Cost to final" value={`-${contribution.toFixed(2)}%`} />
        <Row label="Weight" value={`${category.weight}%`} muted />
      </>
    );
  } else if (kind === "remaining" && pts) {
    body = (
      <>
        <Row label="Still Reachable" value={`${pts.remaining.toFixed(0)} pts ungraded`} />
        <Row label="Up to" value={`+${contribution.toFixed(2)}% of final`} />
        <Row label="Weight" value={`${category.weight}%`} muted />
      </>
    );
  } else {
    body = (
      <>
        <Row label="Weight" value={`${category.weight}% of final`} />
        <Row label="Status" value="No graded points yet" muted />
        <Row
          label="Reachable"
          value={`up to ${contribution.toFixed(2)}% of final`}
        />
      </>
    );
  }

  return (
    <div
      role="tooltip"
      className="fixed pointer-events-none bg-text text-bg py-2.5 px-3 rounded-sm text-sm leading-[1.45] shadow-md z-1000" style={{ left, top, width: TIP_W }}
    >
      <div
        className="font-display text-base font-medium mb-1.5 tracking-[-0.01em]"
      >
        {title}
      </div>
      <div className="flex flex-col gap-[3px]">{body}</div>
    </div>
  );
}

function Row({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div
      className={cn("flex justify-between gap-3", muted ? "opacity-70" : "opacity-100")}
    >
      <span className="text-[color-mix(in_oklch,_var(--bg),_transparent_35%)]">
        {label}
      </span>
      <span className="mono tracking-[-0.01em]">
        {value}
      </span>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Per-category points breakdown — earned vs lost vs still-to-earn.
// ───────────────────────────────────────────────────────────────────────────
interface CategoryPts {
  earned: number;
  lost: number;
  remaining: number;
  total: number;
}

function categoryPoints(
  catId: string,
  assignments: GradedAssignment[],
  dropLowest: number = 0,
): CategoryPts | null {
  const items = assignments.filter(
    (a) =>
      a.category_id === catId &&
      a.points_possible !== null &&
      (a.points_possible as number) > 0,
  );
  if (items.length === 0) return null;

  // Identify which graded items are currently dropped (lowest score %).
  // Drops apply only to graded items — ungraded ones can't be dropped
  // until they have a score to compare. Recomputed locally so optimistic
  // grade edits stay in sync without a server round-trip.
  const drop = Math.max(0, dropLowest);
  let droppedIds: Set<string> = new Set();
  if (drop > 0) {
    const graded = items
      .filter((a) => a.points_earned !== null)
      .map((a) => ({
        id: a.id,
        score: (a.points_earned as number) / (a.points_possible as number),
        possible: a.points_possible as number,
      }));
    graded.sort((a, b) => {
      if (a.score !== b.score) return a.score - b.score;
      if (a.possible !== b.possible) return b.possible - a.possible;
      return a.id.localeCompare(b.id);
    });
    droppedIds = new Set(graded.slice(0, drop).map((g) => g.id));
  }

  const kept = items.filter((a) => !droppedIds.has(a.id));
  const total = kept.reduce((s, a) => s + (a.points_possible as number), 0);
  const keptGraded = kept.filter((a) => a.points_earned !== null);
  const earned = keptGraded.reduce(
    (s, a) => s + (a.points_earned as number),
    0,
  );
  const gradedPossible = keptGraded.reduce(
    (s, a) => s + (a.points_possible as number),
    0,
  );
  const lost = Math.max(0, gradedPossible - earned);
  const remaining = Math.max(0, total - gradedPossible);
  return { earned, lost, remaining, total };
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="py-5 px-6 rounded-md bg-err-soft border border-[color-mix(in_oklab,_var(--err)_20%,_transparent)] flex gap-4 items-center justify-between flex-wrap mt-8"
    >
      <div>
        <div className="font-semibold text-err mb-1">
          We couldn&apos;t load this course.
        </div>
        <div className="text-md text-text-dim">{message}</div>
      </div>
      <button
        type="button"
        className="btn btn--primary py-2 px-4"
        onClick={onRetry}
      >
        Try again
      </button>
    </div>
  );
}

function CoursePageSkeleton({ segmentCount = 4 }: { segmentCount?: number }) {
  return (
    <div>
      <div
        className="flex justify-between items-end gap-8 mb-8 pb-5 border-b border-b-border"
      >
        <div className="flex-1">
          <div className="skeleton w-40 h-3 rounded-xs mb-2.5" />
          <div className="skeleton w-[55%] h-9 rounded-sm" />
        </div>
        <div className="skeleton w-27.5 h-11 rounded-sm" />
      </div>
      <div className="mb-11">
        <div className="skeleton w-35 h-3 rounded-xs mb-3.5" />
        <div className="skeleton w-full h-11.5 rounded-md mb-3" />
        <div className="flex gap-1">
          {Array.from({ length: Math.max(1, segmentCount) }).map((_, i) => (
            <div key={i} className="skeleton flex-1 h-7 rounded-xs" />
          ))}
        </div>
      </div>
      <div className="skeleton w-55 h-4.5 rounded-xs mb-6" />
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="skeleton h-16 rounded-[8px] mb-3" />
      ))}
    </div>
  );
}
