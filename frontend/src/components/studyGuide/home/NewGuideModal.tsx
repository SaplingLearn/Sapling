"use client";
import React from "react";

import Dialog from "@/components/Dialog";
import { DocumentUploadModal } from "@/components/DocumentUploadModal";
import { Skeleton } from "@/components/Skeleton";
import { Button } from "@/components/ui";
import { Switch } from "@/components/ui/Switch";
import type { EnrolledCourse } from "@/lib/api";

import { DepthField, GoalField } from "./ChoiceFields";
import { Field } from "./Field";
import { MaterialTiles } from "./MaterialTiles";
import m from "./newGuide.module.css";
import { scopeKey } from "./newGuideModel";
import { PlannedOutline } from "./PlannedOutline";
import { ClassField, ScopeField } from "./ScopeFields";
import { useCreateGuide } from "./useCreateGuide";
import { useNewGuide, type NewGuide } from "./useNewGuide";
import { usePlan } from "./usePlan";

const HISTORY_LABEL = "Use my quiz history and mastery";

export interface NewGuideModalProps {
  userId: string;
  /** The student's courses in the active term. */
  courses: EnrolledCourse[];
  /** The course list has answered. */
  coursesReady: boolean;
  /** The course list could not be read. */
  coursesFailed: boolean;
  /** Reads the course list again. */
  onRetryCourses: () => void;
  /** The active term's label, "" when no term is picked. */
  semester: string;
  onClose: () => void;
  /** The guide's row exists: the reader takes it from here. */
  onCreated: (guideId: string) => void;
}

/**
 * New study guide: what it is for, how it should read and what it is written
 * from, beside the outline those choices plan. Mounted while open, so every
 * opening starts from the defaults.
 */
export function NewGuideModal({
  userId, courses, coursesReady, coursesFailed, onRetryCourses, semester, onClose, onCreated,
}: NewGuideModalProps) {
  const guide = useNewGuide({ userId, courses, semester });
  const plan = usePlan(userId, guide.request);
  const create = useCreateGuide(userId, onCreated);
  const [uploading, setUploading] = React.useState(false);
  const { form, request } = guide;

  return (
    <>
      <Dialog open onClose={onClose} title="New study guide" width="min(980px, calc(100vw - 32px))">
        <div className={m.dialog} data-testid="guide-new-dialog">
          <div className={m.body}>
            <div className={m.form}>
              <div className={m.pair} onKeyDown={closeOpenList}>
                <ClassField courses={courses} ready={coursesReady} failed={coursesFailed} onRetry={onRetryCourses} value={form.courseId} onChange={guide.pickCourse} />
                <ScopeField scopes={guide.scopes} placeholder={scopePlaceholder(guide)} value={form.scope ? scopeKey(form.scope) : ""} onChange={guide.pickScope} />
              </div>
              <div className={m.choices}>
                <GoalField value={form.goal} onChange={guide.setGoal} />
                <DepthField value={form.depth} onChange={guide.setDepth} />
              </div>
              <Materials guide={guide} onUpload={() => setUploading(true)} />
              <div className={m.history}>
                <span className={m.historyText}>
                  <span className={m.historyTitle}>{HISTORY_LABEL}</span>
                  <span className={m.fieldHint}>More room for what you are weakest on, and your own quiz mistakes.</span>
                </span>
                <Switch checked={form.useHistory} onChange={guide.setUseHistory} label={HISTORY_LABEL} testid="guide-new-history" />
              </div>
            </div>
            <PlannedOutline ready={request !== null} loading={guide.loading} state={plan} />
          </div>
          <footer className={m.foot}>
            {create.error && <p className={m.error} role="alert" data-testid="guide-new-error">{create.error}</p>}
            <Button variant="ghost" data-testid="guide-new-cancel" onClick={onClose}>Cancel</Button>
            <Button
              variant="primary"
              data-testid="guide-new-generate"
              disabled={!request || create.submitting}
              onClick={() => { if (request) void create.submit(request); }}
            >
              {create.submitting ? "Starting…" : "Generate guide"}
            </Button>
          </footer>
        </div>
      </Dialog>
      {/* Beside the dialog, not inside it: its keys must not reach the
          dialog's Escape and focus trap. */}
      <DocumentUploadModal
        open={uploading}
        userId={userId}
        courses={guide.course ? [guide.course] : []}
        onClose={() => setUploading(false)}
        onComplete={() => { void guide.refreshMaterials(); }}
      />
    </>
  );
}

/**
 * Escape on an open Class or Studying-for list closes that list. Without
 * this the dialog takes the key first and closes itself, list and all. The
 * list is closed through its own button, which then has the focus, so the
 * next Escape still reaches the dialog.
 */
function closeOpenList(event: React.KeyboardEvent<HTMLDivElement>) {
  if (event.key !== "Escape") return;
  const button = event.currentTarget.querySelector<HTMLElement>('[aria-haspopup="listbox"][aria-expanded="true"]');
  if (!button) return;
  event.stopPropagation();
  button.click();
  button.focus();
}

function scopePlaceholder(guide: NewGuide): string {
  if (!guide.course) return "Choose a class first";
  return guide.loading ? "Loading…" : "Not available";
}

/** The materials of the chosen class, or why there are none to show yet. */
function Materials({ guide, onUpload }: { guide: NewGuide; onUpload: () => void }) {
  if (!guide.course) return null;
  if (guide.failed) {
    return (
      <Field label="Materials">
        <p className={m.note} role="alert">
          Couldn&apos;t load this class&apos;s materials.{" "}
          <button type="button" className={m.pick} data-testid="guide-new-options-retry" onClick={guide.retry}>Try again</button>
        </p>
      </Field>
    );
  }
  if (guide.loading) {
    return (
      <Field label="Materials">
        <div className={m.tiles} aria-hidden="true">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} height={48} radius="var(--r-md)" />)}
        </div>
      </Field>
    );
  }
  return (
    <MaterialTiles
      materials={guide.materials}
      selected={guide.form.materialIds}
      onToggle={guide.toggleMaterial}
      onSuggested={guide.pickSuggested}
      onAll={guide.pickAll}
      onNone={guide.pickNone}
      onUpload={onUpload}
    />
  );
}
