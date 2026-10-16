/**
 * Route classification: which paths are the signed-in app shell
 * (`src/app/(shell)/*`) as opposed to public/marketing pages, `/auth/*`,
 * onboarding and the rest. FlagsProvider uses it to fetch flags only inside
 * the shell (#620).
 *
 * NOT yet the only copy: middleware.ts (its literal `config.matcher`),
 * app/robots.ts and UserContext.tsx (a plain-prefix match) each still keep
 * their own list, so a new shell route must be added to all of them. The
 * PostHog frontend PR (#675) consolidates them onto this module.
 * Pure constants and string checks only, so the edge runtime can import it.
 */
export const SHELL_PREFIXES = [
  "/dashboard", "/learn", "/quiz", "/study", "/tree",
  "/library", "/calendar", "/social",
  "/settings", "/achievements", "/admin",
  "/gradebook", "/course-planner", "/notetaker", "/profile",
] as const;

/** Segment-boundary match: `/profile` and `/profile/x`, never `/profiles`. */
export function isAppShellRoute(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  return SHELL_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/"));
}
