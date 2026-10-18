"use client";

import React, { Suspense } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Navigation } from "./fa26/Navigation";
import { DesignIcon } from "./fa26/DesignIcon";
import { ReportIssueFlow } from "./ReportIssueFlow";
import { FeedbackFlow } from "./FeedbackFlow";
import { SessionFeedbackGlobal } from "./SessionFeedbackGlobal";
import { AchievementUnlockWatcher } from "./AchievementUnlockWatcher";
import "./fa26/fa26.css";

export function ShellFrame({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/dashboard";
  const [reportOpen, setReportOpen] = React.useState(false);
  return <div className="fa26-shell" data-screen={pathname.split("/")[1] || "dashboard"}>
    <a href="#main-content" className="skip-link">Skip to content</a>
    <Navigation />
    <main id="main-content" tabIndex={-1} data-testid="app-shell" data-scroll-container="" className="fa26-main">
      {children}
    </main>
    <div className="fa26-utilities" aria-label="Account tools">
      <Link href="/settings?section=notifications" aria-label="Notification settings" title="Notification settings"><DesignIcon name="bell" /></Link>
      <Link href="/settings" aria-label="Settings" title="Settings"><DesignIcon name="settings" /></Link>
      <button data-testid="shell-report-issue" type="button" onClick={() => setReportOpen(true)} aria-label="Report an issue" title="Report an issue"><DesignIcon name="report" /></button>
    </div>
    <ReportIssueFlow open={reportOpen} onClose={() => setReportOpen(false)} />
    <Suspense fallback={null}><FeedbackFlow /><SessionFeedbackGlobal /></Suspense>
    <AchievementUnlockWatcher />
  </div>;
}
