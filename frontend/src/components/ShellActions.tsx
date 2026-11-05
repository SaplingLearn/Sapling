"use client";

import { useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "./Icon";
import { ReportIssueFlow } from "./ReportIssueFlow";
import { Tooltip } from "./ui/Tooltip";
import { useLayoutPref } from "@/lib/useLayoutPref";
import { useIsMobile } from "@/lib/useIsMobile";

export function ShellActions() {
  const [reportOpen, setReportOpen] = useState(false);
  const pathname = usePathname();

  return (
    <>
      <div className="shell-actions" role="group" aria-label="Settings and support">
        <Tooltip content="Settings" placement="bottom">
          <Link href="/settings" className="shell-action" aria-label="Settings" aria-current={pathname?.startsWith("/settings") ? "page" : undefined}>
            <Icon name="setting" size={16} />
          </Link>
        </Tooltip>
        <Tooltip content="Report" placement="bottom">
          <button type="button" className="shell-action" aria-label="Report an issue" onClick={() => setReportOpen(true)}>
            <Icon name="error" size={16} />
          </button>
        </Tooltip>
      </div>
      {reportOpen && createPortal(<ReportIssueFlow open onClose={() => setReportOpen(false)} />, document.body)}
    </>
  );
}

export function PageActions() {
  const [layout] = useLayoutPref();
  const isMobile = useIsMobile();
  if (layout !== "sidebar" || isMobile) return null;
  return <div className="shell-page-actions"><ShellActions /></div>;
}
