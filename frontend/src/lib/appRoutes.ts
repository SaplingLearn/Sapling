/**
 * Route classification: which paths are the signed-in app shell
 * (`src/app/(shell)/*`) as opposed to public/marketing pages, `/auth/*`,
 * onboarding and the rest.
 *
 * Mirror of middleware.ts PROTECTED (keep in sync; app/robots.ts mirrors it
 * too). Used by the UserProvider (where a cleared session leaves no usable
 * UI) and by product analytics, which runs only inside the shell.
 */
export const SHELL_PREFIXES = [
  "/dashboard", "/learn", "/quiz", "/study", "/tree",
  "/library", "/calendar", "/social",
  "/settings", "/achievements", "/admin",
  "/gradebook", "/course-planner", "/notetaker", "/profile",
] as const;

export function isAppShellRoute(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  return SHELL_PREFIXES.some((p) => pathname.startsWith(p));
}
