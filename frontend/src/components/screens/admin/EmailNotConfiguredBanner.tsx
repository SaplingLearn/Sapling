import React from "react";

/**
 * Slim warning shown on the Allowlist and Email tabs when
 * `GET /api/admin/email/status` reports Resend isn't configured: emails are
 * recorded server-side but none are actually delivered.
 */
export function EmailNotConfiguredBanner() {
  return (
    <div
      role="status"
      data-testid="email-not-configured-banner"
      className="mb-4 py-2 px-3 rounded-sm bg-warn-soft text-warn text-md"
    >
      Email isn&apos;t configured. Approvals and broadcasts are saved, but no emails go out until Resend is configured.
    </div>
  );
}
