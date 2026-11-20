import React from "react";

/** The nav's destination that hosts the retention check (Study's cards mode). */
export const RETENTION_NAV_HREF = "/study";

/** Spec §13 A126: the small "retention check due" mark the nav shows on its
 *  Study entry while a delayed retention check is open for the student. */
export function RetentionDueDot({ testid, overlay = false }: { testid: string; overlay?: boolean }) {
  return (
    <span
      role="img"
      aria-label="Retention check due"
      title="Retention check due"
      data-testid={testid}
      style={{
        display: "inline-block",
        flexShrink: 0,
        width: 7,
        height: 7,
        borderRadius: 99,
        background: "var(--alert-warn)",
        boxShadow: "0 0 0 2px var(--sidenav-bg, var(--bg-panel))",
        ...(overlay ? { position: "absolute", top: -2, right: -3 } : {}),
      }}
    />
  );
}
