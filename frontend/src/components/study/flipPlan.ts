/**
 * The geometry behind an exam-tab switch (./useFlip.ts): given where the keyed
 * items were and where they are now, which ones slide, which arrive and which
 * go. Pure, so the rule is testable without a browser.
 *
 * An item's box is in its own parent's space (the tile in its column, the
 * column in the grid). A column that slides carries its tiles with it, so a
 * tile slides only by how far it moved INSIDE its column. The same goes for
 * arriving and going: an item inside a parent that arrives or goes does so
 * as part of it, not on its own.
 */

export interface Box { x: number; y: number; w: number; h: number }

export interface FlipItem {
  box: Box;
  /** The key of the tracked item it sits in, or null at the top level. */
  parent: string | null;
}

export interface FlipPlan {
  /** Still there, somewhere else: starts `dx`,`dy` away and slides home. */
  move: { key: string; dx: number; dy: number }[];
  /** New, at the top level or inside a parent that was already there. */
  enter: string[];
  /** Gone, from a parent that is still there (or from the top level). */
  leave: string[];
}

/** The translation that draws a box now at `next` back where it was at `prev`. */
export const offsetBetween = (prev: Box, next: Box) => ({ dx: prev.x - next.x, dy: prev.y - next.y });

/** Under a pixel is rounding, not movement. */
const MIN_MOVE = 1;

export function flipPlan(prev: ReadonlyMap<string, FlipItem>, next: ReadonlyMap<string, FlipItem>): FlipPlan {
  const plan: FlipPlan = { move: [], enter: [], leave: [] };
  for (const [key, item] of next) {
    const was = prev.get(key);
    if (!was) {
      // An item whose parent is new too arrives inside it, not on its own.
      if (!item.parent || prev.has(item.parent)) plan.enter.push(key);
      continue;
    }
    // Boxes in two different parents are not in one space: nothing to slide along.
    if (was.parent !== item.parent) continue;
    const { dx, dy } = offsetBetween(was.box, item.box);
    if (Math.abs(dx) >= MIN_MOVE || Math.abs(dy) >= MIN_MOVE) plan.move.push({ key, dx, dy });
  }
  for (const [key, item] of prev) {
    // An item whose parent went too leaves inside it, not on its own.
    if (!next.has(key) && (!item.parent || next.has(item.parent))) plan.leave.push(key);
  }
  return plan;
}
