"use client";
import React from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { TopBar } from "@/components/TopBar";
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
import { applyCurveToAssignment, hasCurveData } from "@/components/Gradebook/curveUtils";
import { EditWeightsModal } from "@/components/Gradebook/EditWeightsModal";
import { AssignmentList } from "@/components/Gradebook/AssignmentList";
import { AssignmentModal, type AssignmentDraft } from "@/components/Gradebook/AssignmentModal";
import { LetterScaleEditor } from "@/components/Gradebook/LetterScaleEditor";
import { GradescopeSyncModal } from "@/components/Gradebook/GradescopeSyncModal";
import { AmbientOrbs } from "@/components/Gradebook/AmbientOrbs";
import { percentColor } from "@/components/Gradebook/CourseCard";
import { projectGrade, droppedAssignmentIds } from "@/components/Gradebook/GradeProjector";
import { GradePredictorPanel } from "@/components/Gradebook/GradePredictorPanel";
import type {
  GradebookCourse,
  GradeCategory,
  GradedAssignment,
  LetterScaleTier,
} from "@/lib/types";

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

function CurveSettingsModal({
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
  const [mounted, setMounted] = React.useState(false);
  const [avgTarget, setAvgTarget] = React.useState<string>(
    course.curve_avg_target != null ? (course.curve_avg_target * 100).toFixed(0) : "83"
  );
  const [sdDelta, setSdDelta] = React.useState<string>(
    course.curve_sd_delta != null ? (course.curve_sd_delta * 100).toFixed(0) : "10"
  );
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
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
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
      }}
      onClick={onClose}
    >
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "var(--bg)", borderRadius: 12, padding: 24,
        minWidth: 400, maxWidth: 480,
      }}>
        <h3 style={{ margin: "0 0 4px" }}>Bell Curve Settings</h3>
        <p style={{ margin: "0 0 16px", fontSize: 12, color: "var(--text-dim)", lineHeight: 1.5 }}>
          The curve policy comes from your syllabus. The class average maps to a target
          grade; each standard deviation above or below shifts the grade by a fixed amount.
        </p>
        <div style={{ display: "grid", gap: 10, marginBottom: 16 }}>
          <p style={{ margin: 0, fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase",
            letterSpacing: "0.1em", fontFamily: "var(--font-mono)" }}>
            Course Policy (from syllabus)
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <label style={{ flex: 1 }}>
              Average maps to (%)
              <input type="number" min={0} max={100} value={avgTarget}
                onChange={(e) => setAvgTarget(e.target.value)}
                style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }} />
            </label>
            <label style={{ flex: 1 }}>
              Grade per SD (%)
              <input type="number" min={0} max={50} value={sdDelta}
                onChange={(e) => setSdDelta(e.target.value)}
                style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }} />
            </label>
          </div>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 20,
          paddingTop: 12, borderTop: "1px solid var(--border)" }}>
          <button type="button" onClick={onClose}>Cancel</button>
          <button
            type="button"
            disabled={saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onSave({
                  curve_avg_target: toFloat(avgTarget),
                  curve_sd_delta: toFloat(sdDelta),
                });
                onClose();
              } finally { setSaving(false); }
            }}
            style={{
              background: "var(--accent)", color: "#fff",
              border: 0, borderRadius: 6, padding: "6px 14px", cursor: "pointer",
            }}
          >
            {saving ? "Saving…" : "Save"}
          </button>
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

  const refresh = React.useCallback(async () => {
    if (!userId) return;
    setFetchError(null);
    try {
      const fresh = await getGradebookCourse(userId, courseId);
      setData(fresh);
    } catch (err: any) {
      setFetchError(err.message || "Unknown error");
      toast.error(`Couldn't load course: ${err.message}`);
    }
  }, [userId, courseId, toast]);

  const loadInitial = React.useCallback(async () => {
    setLoading(true);
    await refresh();
    setLoading(false);
  }, [refresh]);

  React.useEffect(() => {
    loadInitial();
  }, [loadInitial]);

  const refreshGscope = React.useCallback(async () => {
    if (!userId) return;
    try {
      const status = await getGradescopeStatus(userId);
      if (!status.has_credentials) {
        setGscope({ ready: false, lastSyncedAt: null });
        return;
      }
      const res = await listGradescopeLinks(userId);
      const myLink = res.links.find((l) => l.sapling_course_id === courseId);
      setGscope({
        ready: !!myLink,
        lastSyncedAt: myLink?.last_synced_at ?? status.last_synced_at ?? null,
      });
    } catch {
      setGscope({ ready: false, lastSyncedAt: null });
    }
  }, [userId, courseId]);

  React.useEffect(() => {
    refreshGscope();
  }, [refreshGscope]);

  const directSyncGradescope = React.useCallback(async () => {
    if (!userId) return;
    setGscopeBusy(true);
    try {
      const res = await syncGradescopeCourse(userId, courseId);
      const summary =
        res.failed > 0
          ? `Synced: ${res.inserted} added · ${res.updated} updated · ${res.failed} failed`
          : `Synced: ${res.inserted} added · ${res.updated} updated`;
      if (res.failed > 0) toast.error(summary);
      else toast.success(summary);
      await Promise.all([refresh(), refreshGscope()]);
    } catch (err: any) {
      const msg = err?.message ?? "Sync failed";
      toast.error(msg);
      if (/401|invalid|credentials|link/i.test(msg)) {
        setSyncOpen(true);
        await refreshGscope();
      }
    } finally {
      setGscopeBusy(false);
    }
  }, [userId, courseId, refresh, refreshGscope, toast]);

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
      const prev = data;
      setData({
        ...data,
        assignments: data.assignments.map((a) =>
          a.id === id ? { ...a, points_earned: points } : a,
        ),
      });
      try {
        await updateGradedAssignment(userId, id, { points_earned: points });
        await refresh();
      } catch (err: any) {
        setData(prev);
        toast.error(`Couldn't save: ${err.message}`);
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
    const curvePolicy = predictorCurveEnabled && data.curve_mode === "curved" ? {
      curve_avg_target: data.curve_avg_target ?? 0.83,
      curve_sd_delta: data.curve_sd_delta ?? 0.10,
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
    const policy = {
      curve_avg_target: data.curve_avg_target ?? 0.83,
      curve_sd_delta: data.curve_sd_delta ?? 0.10,
    };
    return data.assignments.map((a) => applyCurveToAssignment(a, policy));
  }, [data]);

  const handleToggleCurveMode = React.useCallback(async () => {
    if (!data || !userId) return;
    const newMode = data.curve_mode === "curved" ? "raw" : "curved";
    setData((prev) => prev ? { ...prev, curve_mode: newMode } : prev);
    try {
      await setCurveSettings(userId, courseId, { curve_mode: newMode });
      await refresh(); // Server recomputes data.percent with the new curve_mode
    } catch {
      setData((prev) => prev ? { ...prev, curve_mode: data.curve_mode } : prev);
    }
  }, [data, userId, courseId, refresh]);

  const handleSaveCurveSettings = React.useCallback(
    async (settings: {
      curve_avg_target: number | null;
      curve_sd_delta: number | null;
    }) => {
      if (!data || !userId) return;
      await setCurveSettings(userId, courseId, {
        curve_mode: data.curve_mode,
        ...settings,
      });
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
    <>
      <AmbientOrbs />
      <TopBar
        breadcrumb={
          <Link href="/gradebook" style={{ color: "var(--text-dim)", textDecoration: "none" }}>
            ← Gradebook
          </Link>
        }
        actions={
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {data && (
              <>
                {hasCurve && (
                  <div style={{ display: "flex", background: "var(--bg-subtle)", borderRadius: 20, padding: 2 }}>
                    {(["raw", "curved"] as const).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        onClick={data.curve_mode !== mode ? handleToggleCurveMode : undefined}
                        style={{
                          padding: "4px 12px",
                          borderRadius: 18,
                          fontSize: 11,
                          fontWeight: 500,
                          background: data.curve_mode === mode ? "var(--accent)" : "transparent",
                          color: data.curve_mode === mode ? "#fff" : "var(--text-dim)",
                          border: 0,
                          cursor: data.curve_mode !== mode ? "pointer" : "default",
                          fontFamily: "var(--font-sans)",
                        }}
                      >
                        {mode === "raw" ? "Raw" : "Curved"}
                      </button>
                    ))}
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => setCurveSettingsOpen(true)}
                  className="btn"
                  title="Bell curve policy"
                  style={{ padding: "4px 12px", fontSize: 12, display: "flex", alignItems: "center", gap: 5 }}
                >
                  <span>⚙</span>
                  <span>Curve</span>
                </button>
              </>
            )}
            <button
              type="button"
              onClick={() => setEditScale(true)}
              className="btn"
              style={{ padding: "4px 12px", fontSize: 12 }}
            >
              Letter Scale
            </button>
          </div>
        }
      />
      <main
        style={{
          padding: "var(--pad-xl)",
          position: "relative",
          minHeight: "calc(100vh - var(--row-h))",
        }}
      >
        <div
          style={{
            position: "relative",
            zIndex: 1,
            maxWidth: 1240,
            margin: "0 auto",
          }}
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
          <EditWeightsModal
            open={editWeights}
            initial={data.categories}
            onClose={() => setEditWeights(false)}
            onSave={async (drafts) => {
              const draftIds = new Set(drafts.map((d) => d.id).filter(Boolean) as string[]);
              for (const c of data.categories) {
                if (!draftIds.has(c.id)) await deleteCategory(userId, c.id);
              }
              await bulkUpdateCategories(userId, courseId, drafts);
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
                await updateGradedAssignment(userId, assignModal.initial.id, draft);
              } else {
                await createGradedAssignment(userId, courseId, draft);
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
              await setLetterScale(userId, courseId, scale);
              await refresh();
            }}
          />

          <GradescopeSyncModal
            open={syncOpen}
            userId={userId}
            saplingCourseId={courseId}
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
    </>
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
      style={{
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "space-between",
        gap: 32,
        marginBottom: 32,
        paddingBottom: 20,
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div
          className="mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.2em",
            textTransform: "uppercase",
            color: "var(--text-muted)",
            marginBottom: 8,
          }}
        >
          {data.course_code}
          {data.semester ? ` · ${data.semester}` : ""}
        </div>
        <h1
          style={{
            fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
            fontWeight: 500,
            fontSize: "clamp(26px, 3vw, 38px)",
            lineHeight: 1.08,
            letterSpacing: "-0.02em",
            color: "var(--text)",
            margin: 0,
          }}
        >
          {data.course_name}
        </h1>
      </div>
      <div
        title={`Letter scale: ${scaleText}`}
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          flexShrink: 0,
          cursor: "help",
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
            fontWeight: 500,
            fontSize: 42,
            lineHeight: 1,
            letterSpacing: "-0.03em",
            color: letterColor,
            fontStyle: isEmpty ? "italic" : "normal",
            opacity: isEmpty ? 0.5 : 1,
          }}
        >
          {isEmpty ? "—" : (data.letter ?? "—")}
        </span>
        <span
          className="mono"
          style={{
            fontSize: 15,
            fontWeight: 600,
            color: letterColor,
            letterSpacing: "-0.02em",
            opacity: isEmpty ? 0.5 : 0.85,
          }}
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
        style={{
          marginBottom: 40,
          padding: "28px 24px",
          borderRadius: "var(--r-md)",
          background: "var(--bg-panel)",
          border: "1px solid var(--border)",
        }}
      >
        <SectionHead label="Composition" onEdit={onEditWeights} />
        <div
          style={{
            fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
            color: "var(--text-dim)",
            fontSize: 15,
            lineHeight: 1.55,
            marginTop: 8,
          }}
        >
          No categories yet. Upload a syllabus or add them by hand to break
          your grade into pieces.
        </div>
      </section>
    );
  }

  return (
    <section style={{ marginBottom: 44 }}>
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
      <div style={{ position: "relative", height: 24, marginTop: 18, marginBottom: 8 }}>
        {ticks.map(({ letter, min }) => (
          <div
            key={letter}
            style={{
              position: "absolute",
              left: `${min}%`,
              top: 0,
              transform: "translateX(-50%)",
              textAlign: "center",
              pointerEvents: "none",
            }}
          >
            <div
              className="mono"
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: "var(--text-dim)",
                lineHeight: 1,
                letterSpacing: "-0.01em",
              }}
            >
              {letter}
            </div>
            <div
              className="mono"
              style={{
                fontSize: 9,
                color: "var(--text-muted)",
                lineHeight: 1.2,
                marginTop: 2,
              }}
            >
              {min}
            </div>
          </div>
        ))}
      </div>

      {/* The composition bar itself */}
      <div
        style={{ position: "relative", width: "100%" }}
        onMouseLeave={() => setTip(null)}
      >
        <div
          style={{
            display: "flex",
            height: 46,
            width: "100%",
            background: "var(--bg-subtle)",
            borderRadius: "var(--r-md)",
            overflow: "hidden",
            border: isPredicted
              ? "1.5px dashed var(--accent-border)"
              : "1px solid var(--border)",
          }}
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
                style={{
                  flex: `${c.weight} 0 0`,
                  display: "flex",
                  cursor: "pointer",
                  borderRight:
                    i < sorted.length - 1
                      ? "1px solid var(--bg-panel)"
                      : "none",
                  minWidth: 0,
                }}
              >
                {isEmptyCat ? (
                  <div
                    style={{
                      width: "100%",
                      height: "100%",
                      backgroundImage:
                        "repeating-linear-gradient(135deg, color-mix(in oklch, var(--sap-500), transparent 70%) 0 6px, transparent 6px 12px)",
                    }}
                    onMouseEnter={onMove("empty", contribRemaining)}
                    onMouseMove={onMove("empty", contribRemaining)}
                  />
                ) : (
                  <>
                    {earnedPctOfSlot > 0 && (
                      <div
                        style={{
                          width: `${earnedPctOfSlot}%`,
                          height: "100%",
                          background: "var(--sap-500)",
                        }}
                        onMouseEnter={onMove("earned", contribEarned)}
                        onMouseMove={onMove("earned", contribEarned)}
                      />
                    )}
                    {lostPctOfSlot > 0 && (
                      <div
                        style={{
                          width: `${lostPctOfSlot}%`,
                          height: "100%",
                          background:
                            "color-mix(in oklch, var(--sap-500), var(--bg-panel) 70%)",
                        }}
                        onMouseEnter={onMove("lost", contribLost)}
                        onMouseMove={onMove("lost", contribLost)}
                      />
                    )}
                    {remainingPctOfSlot > 0 && (
                      <div
                        style={{
                          width: `${remainingPctOfSlot}%`,
                          height: "100%",
                          backgroundImage:
                            "repeating-linear-gradient(135deg, color-mix(in oklch, var(--sap-500), transparent 65%) 0 6px, transparent 6px 12px)",
                        }}
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
            style={{
              position: "absolute",
              left: `${min}%`,
              top: -6,
              bottom: -6,
              width: 1,
              background: "var(--border-strong)",
              transform: "translateX(-0.5px)",
              pointerEvents: "none",
            }}
          />
        ))}

        {/* Now pin */}
        {current !== null && (
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              left: `${current}%`,
              top: -8,
              bottom: -8,
              width: 3,
              background: "var(--text)",
              borderRadius: 1,
              transform: "translateX(-50%)",
              pointerEvents: "none",
              boxShadow: "0 0 0 2px var(--bg)",
            }}
          />
        )}
      </div>

      {/* Category labels under their slots */}
      <div style={{ display: "flex", marginTop: 14 }}>
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
              style={{
                flex: `${c.weight} 0 0`,
                minWidth: 0,
                padding: "0 6px",
                textAlign: "center",
                background: "transparent",
                border: 0,
                borderLeft: i === 0 ? "none" : "1px solid var(--border)",
                cursor: "pointer",
                color: "inherit",
              }}
            >
              <div
                style={{
                  fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
                  fontSize: 12,
                  color: "var(--text)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {c.name}
              </div>
              <div
                className="mono"
                style={{
                  fontSize: 10,
                  color: "var(--text-muted)",
                  marginTop: 2,
                  letterSpacing: "-0.01em",
                }}
              >
                {c.weight}%
                {drop > 0 && (
                  <span
                    style={{ marginLeft: 6, color: "var(--accent)" }}
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
          className="mono"
          style={{
            fontSize: 10,
            color: "var(--warn)",
            marginTop: 12,
            letterSpacing: "-0.01em",
          }}
        >
          Weights sum to {totalWeight.toFixed(0)}%, not 100%. Final percent
          is normalized.
        </div>
      )}

      {/* Legend */}
      <div
        style={{
          display: "flex",
          gap: 20,
          marginTop: 22,
          fontSize: 11,
          color: "var(--text-dim)",
          flexWrap: "wrap",
        }}
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
      style={{
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        gap: 16,
        flexWrap: "wrap",
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 16, minWidth: 0 }}>
        <span
          className="mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--text-muted)",
            fontWeight: 600,
          }}
        >
          {label}
        </span>
        {meta}
      </div>
      <button
        type="button"
        onClick={onEdit}
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: 12,
          fontWeight: 500,
          color: "var(--text-dim)",
          background: "none",
          border: 0,
          padding: 0,
          cursor: "pointer",
          textDecoration: "underline",
          textUnderlineOffset: 3,
          textDecorationColor: "var(--border-strong)",
        }}
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
    <div style={{ display: "flex", alignItems: "baseline", gap: 10, minWidth: 0 }}>
      <span
        style={{
          fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
          fontWeight: 500,
          fontSize: 20,
          lineHeight: 1,
          color: percentColor(current),
          letterSpacing: "-0.01em",
        }}
      >
        {current.toFixed(1)}%
      </span>
      {currentTier && (
        <span
          style={{
            fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
            fontSize: 14,
            color: "var(--text-dim)",
            fontWeight: 400,
          }}
        >
          {currentTier}
        </span>
      )}
      <span
        style={{
          fontSize: 12,
          color: "var(--text-dim)",
          marginLeft: 4,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        · {action}
        {isPredicted && (
          <span style={{ color: "var(--text-muted)", marginLeft: 4 }}>(Predicted)</span>
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
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span
        style={{
          display: "inline-block",
          width: 14,
          height: 10,
          borderRadius: 2,
          ...(isImage ? { backgroundImage: fill } : { background: fill }),
        }}
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

  let title = category.name;
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
      style={{
        position: "fixed",
        left,
        top,
        width: TIP_W,
        pointerEvents: "none",
        background: "var(--text)",
        color: "var(--bg)",
        padding: "10px 12px",
        borderRadius: "var(--r-sm)",
        fontSize: 12,
        lineHeight: 1.45,
        boxShadow: "var(--shadow-md)",
        zIndex: 1000,
      }}
    >
      <div
        style={{
          fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
          fontSize: 14,
          fontWeight: 500,
          marginBottom: 6,
          letterSpacing: "-0.01em",
        }}
      >
        {title}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>{body}</div>
    </div>
  );
}

function Row({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 12,
        opacity: muted ? 0.7 : 1,
      }}
    >
      <span style={{ color: "color-mix(in oklch, var(--bg), transparent 35%)" }}>
        {label}
      </span>
      <span className="mono" style={{ letterSpacing: "-0.01em" }}>
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
        marginTop: 32,
      }}
    >
      <div>
        <div style={{ fontWeight: 600, color: "var(--err)", marginBottom: 4 }}>
          We couldn&apos;t load this course.
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

function CoursePageSkeleton({ segmentCount = 4 }: { segmentCount?: number }) {
  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          gap: 32,
          marginBottom: 32,
          paddingBottom: 20,
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div style={{ flex: 1 }}>
          <div className="skeleton" style={{ width: 160, height: 12, borderRadius: 4, marginBottom: 10 }} />
          <div className="skeleton" style={{ width: "55%", height: 36, borderRadius: 6 }} />
        </div>
        <div className="skeleton" style={{ width: 110, height: 44, borderRadius: 6 }} />
      </div>
      <div style={{ marginBottom: 44 }}>
        <div className="skeleton" style={{ width: 140, height: 12, borderRadius: 4, marginBottom: 14 }} />
        <div className="skeleton" style={{ width: "100%", height: 46, borderRadius: 10, marginBottom: 12 }} />
        <div style={{ display: "flex", gap: 4 }}>
          {Array.from({ length: Math.max(1, segmentCount) }).map((_, i) => (
            <div key={i} className="skeleton" style={{ flex: 1, height: 28, borderRadius: 4 }} />
          ))}
        </div>
      </div>
      <div className="skeleton" style={{ width: 220, height: 18, borderRadius: 4, marginBottom: 24 }} />
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: 64, borderRadius: 8, marginBottom: 12 }} />
      ))}
    </div>
  );
}
