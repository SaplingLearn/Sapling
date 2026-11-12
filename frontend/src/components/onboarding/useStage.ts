"use client";

/**
 * The intro and outro choreography from the Claude Design handoff: the phase
 * the graph and the screens are in, the camera zoom, the two text moments and
 * the white hand-off, on one set of timers.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { GraphPhase, GraphZoom } from "./chapterLayer";

// Intro / outro beats from the handoff, in ms.
//
// `.ob-moment`'s own opacity transition, so the zoom can wait for the intro
// line to be gone rather than racing it.
const INTRO_FADE = 650;
// The handoff — and the pre-#292 animated onboarding it descends from — armed
// the zoom in the SAME tick as the fade-out, so the line was still dissolving
// while the graph pulled in. By request the zoom now starts only once the line
// has fully faded, keeping the original's 650ms beat between the zoom starting
// and the form arriving.
const INTRO_TEXT_IN = 450, INTRO_TEXT_OUT = 1900;
const INTRO_ZOOM = INTRO_TEXT_OUT + INTRO_FADE, INTRO_DONE = INTRO_ZOOM + INTRO_FADE;
const OUTRO_TEXT_IN = 1400, OUTRO_TEXT_OUT = 3050, OUTRO_WHITE = 3450, OUTRO_HANDOFF = 4250;

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export interface Stage {
  phase: GraphPhase;
  zoom: GraphZoom;
  introText: boolean;
  outroText: boolean;
  whiteout: boolean;
  /** Show the screens: at once when resuming a draft (or with reduced
   * motion), otherwise after the intro line and the zoom. */
  enter: (resume: boolean) => void;
  /** Play the outro and call `handoff` when it is over. With reduced motion
   * the white hand-off is immediate. */
  outro: (handoff: () => void) => void;
  /** Back to the screens (a failed save). */
  abort: () => void;
}

export function useStage(): Stage {
  const [phase, setPhase] = useState<GraphPhase>("idle");
  const [zoom, setZoom] = useState<GraphZoom>("rest");
  const [introText, setIntroText] = useState(false);
  const [outroText, setOutroText] = useState(false);
  const [whiteout, setWhiteout] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clear = useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  }, []);
  useEffect(() => clear, [clear]);

  const enter = useCallback((resume: boolean) => {
    clear();
    setIntroText(false);
    setOutroText(false);
    setWhiteout(false);
    if (resume) {
      setZoom("active");
      setPhase("active");
    } else if (prefersReducedMotion()) {
      setPhase("active");
    } else {
      setZoom("rest");
      setPhase("out");
      timers.current = [
        setTimeout(() => setIntroText(true), INTRO_TEXT_IN),
        setTimeout(() => setIntroText(false), INTRO_TEXT_OUT),
        setTimeout(() => setZoom("active"), INTRO_ZOOM),
        setTimeout(() => setPhase("active"), INTRO_DONE),
      ];
    }
  }, [clear]);

  const outro = useCallback((handoff: () => void) => {
    clear();
    setPhase("complete");
    setZoom("active");
    if (prefersReducedMotion()) {
      setWhiteout(true);
      handoff();
      return;
    }
    timers.current = [
      setTimeout(() => setOutroText(true), OUTRO_TEXT_IN),
      setTimeout(() => { setOutroText(false); setZoom("outro"); }, OUTRO_TEXT_OUT),
      setTimeout(() => setWhiteout(true), OUTRO_WHITE),
      setTimeout(handoff, OUTRO_HANDOFF),
    ];
  }, [clear]);

  const abort = useCallback(() => {
    clear();
    setOutroText(false);
    setWhiteout(false);
    setZoom("active");
    setPhase("active");
  }, [clear]);

  return { phase, zoom, introText, outroText, whiteout, enter, outro, abort };
}
