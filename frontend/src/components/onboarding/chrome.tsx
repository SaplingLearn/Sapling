"use client";

/**
 * Everything onboarding draws around the current screen: the exits, the
 * action row, the chapter progress, the key hints, the intro and outro
 * moments and the white hand-off with its status line.
 */
import React from "react";
import { SAPLING_WORDMARK_SRC } from "@/components/SaplingWordmark";
import { CHAPTERS, SCREENS } from "./flow";

const fade = (on: boolean): React.CSSProperties => ({ opacity: on ? 1 : 0 });

/** Sign out, in the corner on every screen and at every width. */
export function TopBar({ active, onSignOut }: { active: boolean; onSignOut: () => void }) {
  return (
    <div className="ob-topbar" style={fade(active)} aria-hidden={!active} inert={!active}>
      <button data-testid="onboarding-sign-out" className="ob-signout" onClick={onSignOut}>
        Sign out
      </button>
    </div>
  );
}

/** Next (or Finish), and under it Back and, on the last screen, Skip. Back is
 * a real button at every width: the Esc hint beside the progress strip is a
 * desktop extra and is hidden on phones. */
export function Actions({ label, canNext, canBack, onNext, onBack, onSkip }: {
  label: string;
  canNext: boolean;
  canBack: boolean;
  onNext: () => void;
  onBack: () => void;
  /** Only on the Connect screen: finish without connecting anything. */
  onSkip?: () => void;
}) {
  return (
    <div className="ob-actions">
      <button data-testid="onboarding-continue" className="ob-primary" disabled={!canNext} onClick={onNext}>
        {label}
      </button>
      <div className="ob-secondaries">
        {canBack && (
          <button data-testid="onboarding-back" className="ob-secondary" onClick={onBack}>
            Back
          </button>
        )}
        {onSkip && (
          <button data-testid="onboarding-skip" className="ob-secondary" onClick={onSkip}>
            Skip for now
          </button>
        )}
      </div>
    </div>
  );
}

/** Six chapter bars, the current one labelled; read out as "Step n of 6". */
export function Progress({ active, screen, done }: { active: boolean; screen: number; done: number[] }) {
  const current = SCREENS[screen].ch;
  return (
    <div className="ob-progress" style={fade(active)} aria-hidden={!active}>
      <p className="ob-sr-only" data-testid="onboarding-step">
        Step {current + 1} of {CHAPTERS.length}: {CHAPTERS[current]}
      </p>
      {CHAPTERS.map((label, i) => {
        const total = SCREENS.filter(s => s.ch === i).length;
        const pos = SCREENS.slice(0, screen + 1).filter(s => s.ch === i).length;
        const isCurrent = current === i;
        const isDone = done.includes(i);
        const fill = isCurrent ? Math.max(8, ((pos - 0.5) / total) * 100) : isDone ? 100 : 0;
        return (
          <div key={label} className="ob-chapter" aria-current={isCurrent ? "step" : undefined} aria-hidden="true">
            <div className="ob-chapter-label">{isCurrent ? label : isDone ? "✓" : ""}</div>
            <div className="ob-chapter-bar"><div style={{ width: `${fill}%` }} /></div>
          </div>
        );
      })}
    </div>
  );
}

/** The design's Enter / Esc hints, clickable with a mouse on wide screens.
 * The real Next and Back buttons are in the action row, so these stay out of
 * the tab order and the accessibility tree. */
export function KeyHints({ active, onNext, onBack }: { active: boolean; onNext: () => void; onBack: () => void }) {
  return (
    <div className="ob-keys" style={fade(active)} aria-hidden="true" inert={!active}>
      <button data-testid="onboarding-next-key" className="ob-key" onClick={onNext} tabIndex={-1}><kbd>Enter</kbd>Next</button>
      <button data-testid="onboarding-back-key" className="ob-key" onClick={onBack} tabIndex={-1}><kbd>Esc</kbd>Back</button>
    </div>
  );
}

/** "Let's Learn About You...": decorative, the first screen's heading takes
 * focus when it arrives. */
export function IntroMoment({ shown, started }: { shown: boolean; started: boolean }) {
  if (!started) return null;
  return (
    <div className="ob-moment ob-moment--intro" style={fade(shown)} aria-hidden="true">
      <div className="ob-moment-glow" />
      <p className="ob-intro-text">Let&apos;s Learn About You...</p>
    </div>
  );
}

/** "Welcome to Sapling". The live region is on the page from the start and
 * filled when the outro begins, so it is read out. */
export function OutroMoment({ shown, complete }: { shown: boolean; complete: boolean }) {
  return (
    <div className="ob-moment ob-moment--outro" style={fade(shown)} aria-live="polite">
      {complete && (
        <>
          <div className="ob-moment-glow" aria-hidden="true" />
          <p className="ob-welcome">
            <span>Welcome to</span>
            <img src={SAPLING_WORDMARK_SRC} alt="Sapling" />
          </p>
        </>
      )}
    </div>
  );
}

/** The white hand-off. While it waits on the save it says so. */
export function Whiteout({ on, settingUp }: { on: boolean; settingUp: boolean }) {
  return (
    <div className="ob-whiteout" style={{ opacity: on ? 1 : 0, pointerEvents: on ? "auto" : "none" }}>
      <p className="ob-setting-up" role="status" data-testid="onboarding-setting-up">
        {on && settingUp ? "Setting up…" : ""}
      </p>
    </div>
  );
}
