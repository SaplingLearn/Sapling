// #164: Dashboard's "Where you left off" cards push /learn?resume=<id>; Tree's
// session rows used ?session=<id> before both callers unified on ?resume=.
// Accept both so any bookmarked/legacy link keeps working. Lives here (not in
// screens/Learn.tsx, which re-exports it) so LoopLearn can read the same deep
// link without importing the screen that mounts it (PKG-13).
export function readResumeParam(params: { get(name: string): string | null }): string | null {
  return params.get("resume") ?? params.get("session");
}
