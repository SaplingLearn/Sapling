"use client";

import React from "react";
import { onReauthRequired, startReauth } from "@/lib/reauth";

/**
 * Admin step-up prompt. Admin routes need a recent Google sign-in (12 h; 30
 * min for destructive actions such as account wipes, role changes, email
 * broadcasts and flag changes — backend services/auth_guard.py). An older
 * session answers 401 `reauth_required`; `fetchJSON` reports it through
 * `onReauthRequired` and this banner offers to sign in again. It does not
 * redirect on its own, so whatever the admin was composing stays on screen
 * until they choose to go.
 *
 * The live region is on the page from the start, so the prompt is announced
 * when it appears.
 */
export function AdminReauthBanner() {
  const [needed, setNeeded] = React.useState(false);
  React.useEffect(() => onReauthRequired(() => setNeeded(true)), []);

  return (
    <div role="status" aria-live="polite" data-testid="admin-reauth-region">
      {needed && (
        <div
          data-testid="admin-reauth-banner"
          className="mt-3 mx-8 mb-0 py-2.5 px-3.5 rounded-sm bg-warn-soft text-warn text-md flex gap-3 items-center flex-wrap"
        >
          <span className="flex-[1_1_240px]">
            For your security, admin actions need a recent sign-in. Sign in with Google again to
            continue — you&apos;ll come back to this page.
          </span>
          <button
            type="button"
            className="btn btn--sm btn--primary"
            data-testid="admin-reauth-signin"
            onClick={startReauth}
          >
            Sign in again
          </button>
        </div>
      )}
    </div>
  );
}
