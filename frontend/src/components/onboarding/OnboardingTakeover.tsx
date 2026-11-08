"use client";

/**
 * Landing → onboarding hand-off, as the original animated onboarding did it
 * (pre-#292): Get Started doesn't navigate and spawns no second graph. The
 * rest of the landing fades out under a veil, the landing hero's own canvas
 * stays on top of it, and onboarding drives that canvas (chapterLayer's
 * graphStage): the intro plays and the same nodes zoom in.
 *
 * Everyone who clicks Get Started is treated as a new student: signed in or
 * not, onboarded or not, the flow plays. A guest signs in at Finish.
 *
 * Onboarding is loaded on demand so the landing bundle doesn't carry it.
 */
import React, { useEffect, useState } from "react";

type OnboardingComponent = React.ComponentType<{ takeover?: boolean }>;

export function OnboardingTakeover() {
  const [Screen, setScreen] = useState<OnboardingComponent | null>(null);

  useEffect(() => {
    let cancelled = false;
    void import("@/components/screens/Onboarding").then(m => {
      if (!cancelled) setScreen(() => m.Onboarding);
    });
    return () => { cancelled = true; };
  }, []);

  // The landing is a long scroll page; it stays put underneath.
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
    const html = document.documentElement;
    const prev = html.style.overflow;
    html.style.overflow = "hidden";
    return () => { html.style.overflow = prev; };
  }, []);

  // The veil fades the landing out from under its hero canvas, which the hero
  // lifts above it (z 150) so the same nodes stay on screen and zoom in.
  return (
    <>
      <div className="ob-veil" aria-hidden="true" />
      {Screen && (
        <div className="ob-takeover" data-testid="onboarding-takeover">
          <Screen takeover />
        </div>
      )}
    </>
  );
}
