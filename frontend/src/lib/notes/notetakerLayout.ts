import type { CSSProperties } from "react";

/**
 * Inline styles for the notetaker's four-rail layout (notes list | editor |
 * detail | chat), per fullscreen mode. Fullscreen collapses the list and the
 * detail rails to zero width and opens the chat rail; every rail animates
 * its flex-basis + opacity. Pure, so `NotetakerScreen` carries no per-mode
 * branches of its own. Key order matches the original inline literals.
 */

const RAIL_TRANSITION =
  "flex-basis var(--dur-slow) var(--ease), opacity var(--dur) var(--ease)";

/** The flex row holding the four rails. */
export function layoutRowStyle(fullscreen: boolean): CSSProperties {
  return {
    flex: 1,
    minHeight: 0,
    display: "flex",
    gap: fullscreen ? 24 : 16,
    padding: fullscreen ? "24px 24px 24px 24px" : "32px 32px 24px",
    transition:
      "gap var(--dur-slow) var(--ease), padding var(--dur-slow) var(--ease)",
  };
}

/** A side rail (list or detail) that is open normally and hidden in fullscreen. */
function sideRailStyle(fullscreen: boolean, basis: string): CSSProperties {
  return {
    flex: fullscreen ? "0 0 0px" : basis,
    minWidth: 0,
    opacity: fullscreen ? 0 : 1,
    overflow: "hidden",
    pointerEvents: fullscreen ? "none" : undefined,
    transition: RAIL_TRANSITION,
  };
}

export function notesListRailStyle(fullscreen: boolean): CSSProperties {
  return sideRailStyle(fullscreen, "0 0 clamp(260px, 22%, 320px)");
}

export function noteDetailRailStyle(fullscreen: boolean): CSSProperties {
  return sideRailStyle(fullscreen, "0 0 clamp(280px, 22%, 340px)");
}

/** The editor's width frame: unbounded normally, capped and centred in fullscreen. */
export function editorFrameStyle(fullscreen: boolean): CSSProperties {
  return {
    width: "100%",
    maxWidth: fullscreen ? "min(1200px, 96%)" : "none",
    display: "flex",
    transition: "max-width var(--dur-slow) var(--ease)",
  };
}

/** The chat rail: hidden normally, open only in fullscreen. */
export function chatRailStyle(fullscreen: boolean): CSSProperties {
  return {
    flex: fullscreen ? "0 0 clamp(300px, 24%, 380px)" : "0 0 0px",
    minWidth: 0,
    opacity: fullscreen ? 1 : 0,
    overflow: "hidden",
    pointerEvents: fullscreen ? undefined : "none",
    display: "flex",
    flexDirection: "column",
    paddingTop: fullscreen ? 32 : 0,
    paddingBottom: fullscreen ? 32 : 0,
    transition:
      "flex-basis var(--dur-slow) var(--ease), opacity var(--dur) var(--ease), padding var(--dur-slow) var(--ease)",
  };
}
