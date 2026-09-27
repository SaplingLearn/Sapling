/**
 * Route classification: which paths are the signed-in app shell
 * (`src/app/(shell)/*`) as opposed to public/marketing pages, `/auth/*`,
 * onboarding and the rest.
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

/** Segment-boundary match: `/profile` and `/profile/x`, never `/profiles`. */
export function isAppShellRoute(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  return SHELL_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/"));
}
