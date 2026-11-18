/** A modal dialog (the AI notice, the crisis-support card, the phone's tutor
 *  drawer) owns focus while it is open: nothing on the screen behind it may
 *  take it (spec §13 A135). */
export const modalOpen = (): boolean =>
  typeof document !== "undefined" && document.querySelector('[aria-modal="true"]') !== null;
