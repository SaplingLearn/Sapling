"use client";

/**
 * Landing → onboarding hand-off, as the original animated onboarding did it
 * (pre-#292): Get Started doesn't navigate. Onboarding mounts over the landing
 * and fades in, so the landing's nodes cross-fade into the onboarding graph's
 * original colors, then the intro plays and the graph zooms in.
 *
 * Onboarding is loaded on demand so the landing bundle doesn't carry it.
 */
import React, { useEffect, useState } from "react";

type OnboardingComponent = React.ComponentType;

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

  if (!Screen) return null;
  return (
    <div className="ob-takeover" data-testid="onboarding-takeover">
      <Screen />
    </div>
  );
}
