"use client";

/**
 * Onboarding is enforced (owner decision, 2026-11-12): a signed-in, approved
 * student who hasn't finished it is sent to /onboarding from any app page.
 *
 * The middleware does this on every server request (it already reads
 * GET /api/auth/me there); this gate covers what the server doesn't see — a
 * navigation inside the app, or a /me the middleware couldn't read. It acts
 * only on a definite `false` from /api/auth/me (UserContext's
 * `onboardingCompleted`): unknown (null) renders the page as before, so a
 * slow or failed read never blocks the app. Onboarding marks the account
 * onboarded before it hands off here, so its own hand-off is never bounced.
 */
import React, { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/context/UserContext";

export const ONBOARDING_ROUTE = "/onboarding";

export function OnboardingGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { userReady, isAuthenticated, onboardingCompleted } = useUser();
  const unfinished = userReady && isAuthenticated && onboardingCompleted === false;

  useEffect(() => {
    if (unfinished) router.replace(ONBOARDING_ROUTE);
  }, [unfinished, router]);

  // Nothing of the app (or its data requests) for a student on their way out.
  if (unfinished) return null;
  return <>{children}</>;
}
