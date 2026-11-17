"use client";
/**
 * BUILD: put a set together by hand. The course's concept map (the Study
 * hub's roadmap columns) with the tray beside it (under it when narrow).
 *
 * It is a step entered on purpose from the home: "Build one by hand" (nothing
 * ticked), a deck (its set loaded), "Merge into one" (the union ticked), or
 * "Sort it" (the described concepts ticked, with what the sort did said at the
 * top). The selection, its options and the set it came from are the page's
 * `Draft`; saving returns to the home, where the new deck is.
 */
import React from "react";
import { ConceptMap } from "./ConceptMap";
import {
  saveState,
  summarize,
  type Draft,
  type DraftAction,
  type ExamRef,
  type HomeModel,
} from "./flashcardsModel";
import { selectionMix } from "./decksModel";
import h from "./home.module.css";
import { Tray } from "./Tray";
import type { SetsState } from "./useFlashcardsData";
import { useSetActions } from "./useSetActions";
import type { StartProgress } from "./useStart";

export interface SetBuilderProps {
  /** "" for a student with no course. */
  courseId: string;
  hasConcepts: boolean;
  model: HomeModel;
  /** Every dated exam of the course (a saved set may be for one). */
  exams: ExamRef[];
  sets: SetsState;
  draft: Draft;
  dispatch: React.Dispatch<DraftAction>;
  progress: StartProgress | null;
  running: boolean;
  notice: string | null;
  /** What "Sort it" did, when that is how the builder was opened. */
  note: string;
  onStart: () => void;
  /** A set was saved: back to the home, where it now is. */
  onSaved: () => void;
}

export function SetBuilder(props: SetBuilderProps) {
  const { model, draft, dispatch, sets } = props;
  const actions = useSetActions(sets, model.columns, props.exams, dispatch);
  const onlyDue = model.index.showDue && draft.onlyDue;
  const summary = summarize(draft.selected, model.index, onlyDue);
  // A set belongs to a course: with none there is nothing to save it under.
  const save = saveState(draft, sets.sets);
  const hasCourse = !!props.courseId;
  // A failed save has already said so, and the tray stays as it was.
  const saveDraft = async (mode: "create" | "update") => {
    if (await actions.save(draft, mode)) props.onSaved();
  };

  return (
    <div className={h.home}>
      {props.note && <p className={h.buildNote} role="status" data-testid="flashcards-build-note">{props.note}</p>}
      <div className={h.body}>
        <ConceptMap
          columns={model.columns}
          hasConcepts={props.hasConcepts}
          hasCourse={hasCourse}
          selected={draft.selected}
          onToggle={name => dispatch({ type: "toggle", name })}
          onColumn={(names, on) => dispatch({ type: "many", names, on })}
          onRemoveOwn={name => dispatch({ type: "uncustom", name })}
        />
        <Tray
          draft={draft}
          summary={summary}
          mix={selectionMix(model.columns, draft.selected)}
          showDue={model.index.showDue}
          save={hasCourse ? save : { ...save, enabled: false, canSaveAsNew: false }}
          saving={actions.saving}
          progress={props.progress}
          running={props.running}
          notice={props.notice}
          onOption={patch => dispatch({ type: "option", patch })}
          onName={value => dispatch({ type: "name", value })}
          onStart={props.onStart}
          onSave={mode => { void saveDraft(mode); }}
          onClear={() => dispatch({ type: "clear" })}
        />
      </div>
    </div>
  );
}
