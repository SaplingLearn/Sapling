"use client";
import { Icon } from "@/components/Icon";
import type { MaterialOption } from "@/lib/studyGuide/types";

import { MAX_MATERIALS, atCap } from "./newGuideModel";
import m from "./newGuide.module.css";

export interface MaterialTilesProps {
  materials: MaterialOption[];
  /** The selected material ids. */
  selected: string[];
  onToggle: (id: string) => void;
  onSuggested: () => void;
  onAll: () => void;
  onNone: () => void;
  onUpload: () => void;
}

/**
 * The class's materials as toggle tiles, with the quick picks over them and a
 * last tile that adds one. Past the cap a tile can be turned off but not on.
 */
export function MaterialTiles({ materials, selected, onToggle, onSuggested, onAll, onNone, onUpload }: MaterialTilesProps) {
  const full = atCap(selected);
  return (
    <div className={m.field}>
      <div className={m.fieldHead}>
        <span className="label-micro">Materials</span>
        <span className={m.fieldHint} data-testid="guide-new-materials-count">
          {materials.length ? `${selected.length} of ${materials.length} selected` : "This class has none yet. Add one to make a guide."}
        </span>
        {materials.length > 0 && (
          <span className={m.picks}>
            <button type="button" className={m.pick} data-testid="guide-new-materials-suggested" onClick={onSuggested}>Suggested</button>
            <button type="button" className={m.pick} data-testid="guide-new-materials-all" onClick={onAll}>All</button>
            <button type="button" className={m.pick} data-testid="guide-new-materials-none" onClick={onNone}>None</button>
          </span>
        )}
      </div>
      <ul className={m.tiles}>
        {materials.map(material => {
          const on = selected.includes(material.id);
          return (
            <li key={material.id}>
              <button
                type="button"
                className={m.tile}
                aria-pressed={on}
                aria-disabled={(full && !on) || undefined}
                data-testid={`guide-new-material-${material.id}`}
                onClick={() => onToggle(material.id)}
              >
                <span className={m.tileCheck} aria-hidden="true">{on && <Icon name="check" size={11} />}</span>
                <span className={m.tileText}>
                  <span className={m.tileName}>{material.file_name}</span>
                  <span className={m.tileMeta}>{material.category.replace(/_/g, " ")}</span>
                </span>
              </button>
            </li>
          );
        })}
        <li>
          <button type="button" className={`${m.tile} ${m.tileAdd}`} data-testid="guide-new-upload" onClick={onUpload}>
            <Icon name="plus" size={12} /> Add from Library or upload
          </button>
        </li>
      </ul>
      {full && (
        <p className={m.note} role="status" data-testid="guide-new-materials-cap">
          A guide uses up to {MAX_MATERIALS} materials. Turn one off to add another.
        </p>
      )}
    </div>
  );
}
