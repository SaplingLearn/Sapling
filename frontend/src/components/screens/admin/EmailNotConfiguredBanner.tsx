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
      style={{
        marginBottom: 16,
        padding: "8px 12px",
        borderRadius: "var(--r-sm)",
        background: "var(--warn-soft)",
        color: "var(--warn)",
        fontSize: 13,
      }}
    >
      Email isn&apos;t configured. Approvals and broadcasts are saved, but no emails go out until Resend is configured.
    </div>
  );
}
