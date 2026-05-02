"use client";
import React from "react";
import Link from "next/link";
import { TopBar } from "@/components/TopBar";
import { useUser } from "@/context/UserContext";
import { useToast } from "@/components/ToastProvider";
import {
  getGradebookCourse, bulkUpdateCategories, deleteCategory,
  createGradedAssignment, updateGradedAssignment, deleteGradedAssignment,
  setLetterScale,
} from "@/lib/api";
import { CategoryPanel } from "@/components/Gradebook/CategoryPanel";
import { EditWeightsModal } from "@/components/Gradebook/EditWeightsModal";
import { AssignmentList } from "@/components/Gradebook/AssignmentList";
import { AssignmentModal, type AssignmentDraft } from "@/components/Gradebook/AssignmentModal";
import { LetterScaleEditor } from "@/components/Gradebook/LetterScaleEditor";
import type { GradebookCourse, GradedAssignment } from "@/lib/types";

interface Props { courseId: string; }

export function GradebookCourseScreen({ courseId }: Props) {
  const { userId, userReady } = useUser();
  const toast = useToast();

  const [data, setData] = React.useState<GradebookCourse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [editWeights, setEditWeights] = React.useState(false);
  const [editScale, setEditScale] = React.useState(false);
  const [assignModal, setAssignModal] = React.useState<{ open: boolean; initial: GradedAssignment | null }>({
    open: false, initial: null,
  });

  const reload = React.useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      setData(await getGradebookCourse(userId, courseId));
    } catch (err: any) {
      toast.error(`Couldn't load course: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [userId, courseId, toast]);

  React.useEffect(() => { reload(); }, [reload]);

  if (!userReady || !userId) return null;
  if (loading || !data) return <main style={{ padding: 32 }}>Loading…</main>;

  return (
    <>
      <TopBar
        breadcrumb={<Link href="/gradebook" style={{ color: "var(--text-dim)" }}>← Gradebook</Link>}
        title={`${data.course_code} · ${data.course_name}`}
        subtitle={data.semester}
        actions={
          <button
            type="button"
            onClick={() => setEditScale(true)}
            style={{
              fontSize: 12, padding: "4px 10px",
              border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)",
            }}
          >
            Letter scale
          </button>
        }
      />
      <main style={{ padding: 32 }}>
        <div
          style={{
            marginBottom: 16,
            display: "flex", justifyContent: "flex-end", alignItems: "baseline", gap: 8,
          }}
        >
          <span style={{ fontSize: 28, fontWeight: 700, color: "var(--accent)" }}>
            {data.letter ?? "—"}
          </span>
          <span style={{ color: "var(--text-dim)" }}>
            {data.percent !== null ? `${data.percent.toFixed(1)}%` : "No grades yet"}
          </span>
        </div>
        <CategoryPanel
          categories={data.categories}
          onEdit={() => setEditWeights(true)}
        />
        <AssignmentList
          assignments={data.assignments}
          categories={data.categories}
          onAdd={() => setAssignModal({ open: true, initial: null })}
          onEditFull={(a) => setAssignModal({ open: true, initial: a })}
          onSyncGradescope={() => toast.info("Gradescope integration coming soon")}
          onEditGrade={async (id, points) => {
            await updateGradedAssignment(userId, id, { points_earned: points });
            await reload();
          }}
        />
      </main>

      <EditWeightsModal
        open={editWeights}
        initial={data.categories}
        onClose={() => setEditWeights(false)}
        onSave={async (drafts) => {
          // Detect deletions: any existing id missing from drafts.
          const draftIds = new Set(drafts.map((d) => d.id).filter(Boolean) as string[]);
          for (const c of data.categories) {
            if (!draftIds.has(c.id)) await deleteCategory(userId, c.id);
          }
          await bulkUpdateCategories(userId, courseId, drafts);
          await reload();
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
          await reload();
        }}
        onDelete={
          assignModal.initial
            ? async () => {
                await deleteGradedAssignment(userId, assignModal.initial!.id);
                await reload();
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
          await reload();
        }}
      />
    </>
  );
}
