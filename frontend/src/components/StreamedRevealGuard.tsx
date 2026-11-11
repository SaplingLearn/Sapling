"use client";

import { useStreamedRevealGuard } from "@/lib/streamedReveal";

/** Rendered first in the root layout's <body>, above every provider: its
 *  reveal runs in the hydration commit, before any post-hydration update can
 *  render the page again — see lib/streamedReveal.ts. Renders nothing. */
export function StreamedRevealGuard() {
  useStreamedRevealGuard();
  return null;
}
