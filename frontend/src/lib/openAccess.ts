"use client";
import { useEffect, useState } from "react";

import { fetchFlags } from "@/lib/flags";

/**
 * Whether the waitlist requirement is lifted (`open_access` on,
 * docs/design/open-access-gate.md), for the public pages, which sit outside
 * the app shell where `useFlag` answers "off". `GET /api/flags` answers a
 * signed-out visitor too. Fails closed: false until the answer is in, and on
 * any error or a degraded store, so the page offers the waitlist (always a
 * safe offer: a waitlisted visitor whose gate is open still gets in by
 * signing in).
 */
export const OPEN_ACCESS_FLAG = "open_access";

export function useOpenAccess(): boolean {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let live = true;
    fetchFlags().then(
      (flags) => { if (live) setOpen(flags[OPEN_ACCESS_FLAG] === "on"); },
      () => { if (live) setOpen(false); },
    );
    return () => { live = false; };
  }, []);
  return open;
}
