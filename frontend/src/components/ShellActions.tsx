"use client";

import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "./Icon";
import { ReportIssueFlow } from "./ReportIssueFlow";
import { Tooltip } from "./ui/Tooltip";
import { useCornerDodge } from "./useCornerDodge";
import styles from "./ShellActions.module.css";

/** `showSettings={false}` drops the gear: in the sidebar layout Settings
 *  lives in the rail's account footer, so only Report remains.
 *  `tooltipPlacement` follows where the cluster sits (top bar → below it,
 *  bottom-right corner → above it). */
export function ShellActions({
  showSettings = true,
  tooltipPlacement = "bottom",
}: { showSettings?: boolean; tooltipPlacement?: "top" | "bottom" } = {}) {
  const [reportOpen, setReportOpen] = useState(false);
  const pathname = usePathname();

  return (
    <>
      <div className="shell-actions" role="group" aria-label={showSettings ? "Settings and support" : "Support"}>
        {showSettings && (
          <Tooltip content="Settings" placement={tooltipPlacement}>
            <Link href="/settings" className="shell-action" aria-label="Settings" aria-current={pathname?.startsWith("/settings") ? "page" : undefined}>
              <Icon name="setting" size={16} />
            </Link>
          </Tooltip>
        )}
        <Tooltip content="Report" placement={tooltipPlacement}>
          <button type="button" className="shell-action" aria-label="Report an issue" onClick={() => setReportOpen(true)}>
            <Icon name="error" size={16} />
          </button>
        </Tooltip>
      </div>
      {reportOpen && createPortal(<ReportIssueFlow open onClose={() => setReportOpen(false)} />, document.body)}
    </>
  );
}

/** The sidebar layout's Report button: rendered ONCE by `ShellFrame`, pinned
 *  to the content column's bottom-right corner, so it sits in the same spot
 *  on every page instead of wherever each page's header happened to put it.
 *  (The top-nav layout keeps it in the bar via `TopNav`.) That corner is also
 *  where pages dock their own controls, so it rises above any control under
 *  it (`useCornerDodge`) instead of covering it. */
export function ShellCornerActions() {
  const ref = useRef<HTMLDivElement>(null);
  const pathname = usePathname() ?? "";
  useCornerDodge(ref, pathname);
  return (
    <div ref={ref} className={`shell-corner-actions ${styles.corner}`} data-testid="shell-corner-actions">
      <ShellActions showSettings={false} tooltipPlacement="top" />
    </div>
  );
}
