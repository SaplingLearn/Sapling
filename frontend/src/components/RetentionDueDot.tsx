import React from "react";
import styles from "./RetentionDueDot.module.css";

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
      className={overlay ? `${styles.dot} ${styles.overlay}` : styles.dot}
    />
  );
}
