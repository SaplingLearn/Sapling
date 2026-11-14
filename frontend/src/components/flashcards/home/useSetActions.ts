"use client";
/**
 * What the page does to saved sets: load one into the builder, save the
 * builder's draft, rename, delete. Each write toasts its own outcome.
 *
 * A set stores concept NAMES: the ones on the course map load under the map's
 * spelling, the rest as the student's own concepts. Only a blank or over-long
 * name is left out (and said so).
 */
import React from "react";
import type { FlashcardSet } from "@/lib/flashcardSetsApi";
import { useToast } from "../../ToastProvider";
import {
  draftPayload,
  plural,
  resolveSet,
  type Draft,
  type DraftAction,
  type ExamRef,
  type MapColumn,
} from "./flashcardsModel";
import type { SetsState } from "./useFlashcardsData";

export function useSetActions(
  sets: SetsState,
  columns: MapColumn[],
  exams: ExamRef[],
  dispatch: React.Dispatch<DraftAction>,
) {
  const toast = useToast();
  const [saving, setSaving] = React.useState(false);

  /** Puts the set, and nothing else, in the draft. False when it holds
   *  nothing that can be used. */
  const load = (set: FlashcardSet): boolean => {
    const r = resolveSet(set.concepts, columns);
    if (!r.names.length) {
      toast.warn(`"${set.name}" has no concepts that can be used.`);
      return false;
    }
    if (r.dropped) toast.info(`${plural(r.dropped, "blank or invalid name")} in "${set.name}" ${r.dropped === 1 ? "was" : "were"} left out.`);
    dispatch({ type: "reset" });
    dispatch({ type: "load", set, names: r.names, custom: r.custom });
    return true;
  };

  /** Saves the draft; resolves with the saved set, or null (already toasted). */
  const save = async (draft: Draft, mode: "create" | "update"): Promise<FlashcardSet | null> => {
    if (saving) return null;
    setSaving(true);
    const { exam_id, ...payload } = draftPayload(draft);
    const loaded = mode === "update" ? (sets.sets ?? []).find(s => s.id === draft.setId) : undefined;
    // The server checks an exam id is still one of the student's. An update
    // sends it only when it changed, so a set whose exam was since deleted can
    // still be saved; a new set keeps it only while the exam is there.
    const saved = loaded
      ? await sets.update(loaded.id, exam_id === loaded.exam_id ? payload : { ...payload, exam_id })
      : await sets.create({ ...payload, exam_id: exams.some(e => e.id === exam_id) ? exam_id : null });
    setSaving(false);
    if (!saved) return null;
    dispatch({ type: "saved", set: saved });
    toast.success(mode === "update" ? `Updated "${saved.name}".` : `Saved "${saved.name}".`);
    return saved;
  };

  const rename = async (set: FlashcardSet, name: string) => {
    const saved = await sets.update(set.id, { name });
    if (saved) dispatch({ type: "renamed", set: saved });
    return !!saved;
  };

  const remove = async (set: FlashcardSet) => {
    if (!(await sets.remove(set.id))) return;
    dispatch({ type: "deleted", setId: set.id });
    toast.success(`Deleted "${set.name}".`);
  };

  return { saving, load, save, rename, remove };
}
