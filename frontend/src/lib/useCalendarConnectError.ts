"use client";
import React from "react";
import { useToast } from "@/components/ToastProvider";
import { CALENDAR_ERROR_PARAM, calendarConnectError } from "@/lib/calendarConnect";

/**
 * A Google Calendar connect that failed lands on its `next` page with
 * `?calendar_error=<code>` (backend routes/calendar_connect.py), e.g.
 * onboarding's hand-off to /gradebook. On a page other than /calendar (which
 * explains it itself) this says why once, then drops the code from the URL.
 * Reads window.location, so the page needs no Suspense boundary for it.
 */
export function useCalendarConnectError(): void {
  const toast = useToast();
  React.useEffect(() => {
    const url = new URL(window.location.href);
    const code = url.searchParams.get(CALENDAR_ERROR_PARAM);
    if (!code) return;
    toast.error(calendarConnectError(code));
    url.searchParams.delete(CALENDAR_ERROR_PARAM);
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  }, [toast]);
}
