/**
 * Route classification: which paths are the signed-in app shell
 * (`src/app/(shell)/*`) as opposed to public/marketing pages, `/auth/*`,
 * onboarding and the rest. FlagsProvider uses it to fetch flags only inside
 * the shell (#620).
 *
 * The ONE list: middleware.ts (auth gating), app/robots.ts (disallow), the
 * UserProvider (where a cleared session leaves no usable UI) and product
 * analytics (which runs only inside the shell) all import it. Pure constants
 * and string checks only — middleware.ts runs on the edge runtime.
 * (middleware.ts's `config.matcher` must stay a literal for Next's static
 * analysis; middleware.test.ts pins it to this list.)
 */
export const SHELL_PREFIXES = [
  "/dashboard", "/learn", "/quiz", "/study", "/tree",
  "/library", "/calendar", "/social",
  "/settings", "/achievements", "/admin",
  "/gradebook", "/course-planner", "/notetaker", "/profile",
] as const;

function underPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(prefix + "/");
}

/** Segment-boundary match: `/profile` and `/profile/x`, never `/profiles`. */
export function isAppShellRoute(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  return SHELL_PREFIXES.some((p) => underPrefix(pathname, p));
}

/**
 * First-run onboarding. Not part of the shell (no nav, no analytics, no
 * flags), but gated by the middleware like it: a signed-out visitor goes
 * through sign-in, an unapproved account to /pending, and an account that
 * has finished onboarding to /dashboard.
 */
export const ONBOARDING_PREFIX = "/onboarding";

export function isOnboardingRoute(pathname: string | null | undefined): boolean {
  return !!pathname && underPrefix(pathname, ONBOARDING_PREFIX);
}
