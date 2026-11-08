/**
 * One feedback prompt on screen at a time (#762).
 *
 * ShellFrame mounts two independent full-screen feedback modals —
 * FeedbackFlow (the passive "What's clicking?" pulse) and
 * SessionFeedbackGlobal (the navigate-away-from-/learn session prompt). Each
 * decides on its own when to open, so nothing stopped both opening at once.
 * Each now claims this slot before it opens and releases it when it closes;
 * a prompt that finds the slot taken simply doesn't open this time (and
 * records no cooldown, so it isn't spent).
 *
 * Module state is fine here: both prompts live in the one app shell, and the
 * slot only ever holds a short owner name.
 */

export type FeedbackOwner = "global" | "session";

let holder: FeedbackOwner | null = null;

/** Take the slot. True when it was free or already ours. */
export function tryClaimFeedbackSlot(owner: FeedbackOwner): boolean {
  if (holder !== null && holder !== owner) return false;
  holder = owner;
  return true;
}

/** Give the slot back. A no-op for an owner that doesn't hold it. */
export function releaseFeedbackSlot(owner: FeedbackOwner): void {
  if (holder === owner) holder = null;
}

export function __resetFeedbackSlotForTests(): void {
  holder = null;
}
