"use client";
/**
 * The tray beside the map: what is ticked, the options a review starts with,
 * a name to keep the selection under, and the two buttons.
 *
 * Every line that changes with a tick keeps its height (see .trayLine and
 * .status), so ticking a tile never moves the options or the buttons.
 */
import React from "react";
import { SegmentedControl } from "../../ui/SegmentedControl";
import { Switch } from "../../ui/Switch";
import { PER_CONCEPT, plural, type Draft, type PerConcept, type SaveState } from "./flashcardsModel";
import h from "./home.module.css";
import { startStatus, type StartProgress } from "./useStart";

export interface TrayProps {
  draft: Draft;
  /** `cards` already honours "Only what's due". */
  summary: { concepts: number; cards: number; missing: string[] };
  /** How the selection divides over the map's columns, in their colours. */
  mix: { palette: string; label: string; count: number }[];
  /** Due dates are tracked: "Only what's due" is offered. */
  showDue: boolean;
  save: SaveState;
  saving: boolean;
  progress: StartProgress | null;
  /** A review is being started. */
  running: boolean;
  notice: string | null;
  onOption: (patch: Partial<Pick<Draft, "onlyDue" | "shuffle" | "perConcept">>) => void;
  onName: (value: string) => void;
  onStart: () => void;
  onSave: (mode: "create" | "update") => void;
  /** Untick everything. */
  onClear: () => void;
}

/** The line under the count: what Start will do about concepts with no cards. */
function selectionLine(summary: TrayProps["summary"], onlyDue: boolean): string {
  if (!summary.concepts) return "Tick concepts or a whole column.";
  const bare = summary.missing.length;
  if (!bare) return "";
  const verb = bare === 1 ? "has" : "have";
  return onlyDue
    ? `${bare} ${verb} no cards yet.`
    : `${bare} ${verb} no cards yet and will be generated.`;
}

export function Tray(props: TrayProps) {
  const { draft, summary, showDue, save, saving, running } = props;
  const onlyDue = showDue && draft.onlyDue;
  const willGenerate = !onlyDue && summary.missing.length > 0;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (save.enabled && !saving) props.onSave(save.mode);
  };
  return (
    <aside aria-label="Your selection" className={h.tray}>
      <div className={h.trayHead}>
        <span className="label-micro">Your selection</span>
        {/* Always rendered so the head keeps its height; hidden with nothing ticked. */}
        <button type="button" className={`btn btn--ghost btn--sm ${h.trayClear}`} onClick={props.onClear}
          style={{ visibility: summary.concepts ? "visible" : "hidden" }}>
          Clear
        </button>
      </div>
      <div className={`h-serif ${h.trayCount}`} data-testid="flashcards-selection">
        {summary.concepts ? `${plural(summary.concepts, "concept")} · ${plural(summary.cards, "card")}` : "Nothing ticked yet"}
      </div>
      {/* The selection in the columns' colours. Always there (an empty track
          with nothing ticked), so a tick does not move what is under it. */}
      <div className={h.trayMix} aria-hidden="true" data-testid="flashcards-selection-mix">
        {props.mix.map(part => (
          <i key={part.label} className={h.trayMixSeg} data-palette={part.palette} style={{ flexGrow: part.count }} title={`${part.label}: ${part.count}`} />
        ))}
      </div>
      <div className={h.trayLine}>{selectionLine(summary, onlyDue)}</div>

      <div className={h.opts}>
        {showDue && (
          <div className={h.opt}>
            <span>Only what&apos;s due</span>
            <Switch checked={draft.onlyDue} onChange={v => props.onOption({ onlyDue: v })} label="Only what's due" />
          </div>
        )}
        <div className={h.opt}>
          <span>Shuffle</span>
          <Switch checked={draft.shuffle} onChange={v => props.onOption({ shuffle: v })} label="Shuffle" />
        </div>
        <div className={`${h.opt}${willGenerate ? "" : ` ${h.optOff}`}`} title={willGenerate ? undefined : "Used when a ticked concept has no cards yet"}>
          <span>New cards per concept</span>
          <SegmentedControl<PerConcept>
            ariaLabel="New cards per concept"
            options={PER_CONCEPT.map(n => ({ value: n, label: String(n), disabled: !willGenerate }))}
            value={draft.perConcept}
            onChange={v => props.onOption({ perConcept: v })}
          />
        </div>
      </div>

      <form onSubmit={submit}>
        <div className={h.nameRow}>
          <label className="label-micro" htmlFor="flashcards-set-name">Set name</label>
          {save.canSaveAsNew && (
            <button type="button" className={h.linkBtn} onClick={() => props.onSave("create")} disabled={saving}>Save as new</button>
          )}
        </div>
        <input
          id="flashcards-set-name"
          className={h.field}
          placeholder="Name this set (optional)"
          value={draft.name}
          maxLength={80}
          autoComplete="off"
          onChange={e => props.onName(e.target.value)}
        />
        <div className={h.trayActions}>
          <button type="button" className={`btn btn--primary ${h.start}`} onClick={props.onStart} disabled={!summary.concepts || running}>
            {running ? "Starting…" : "Start"}
          </button>
          <button type="submit" className={`btn ${h.save}`} disabled={!save.enabled || saving}>
            {save.label}
          </button>
        </div>
      </form>
      <div className={h.status} role="status">{startStatus(props.progress, running, props.notice)}</div>
    </aside>
  );
}
