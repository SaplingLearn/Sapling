import React, { Suspense } from "react";
import { TopNav } from "@/components/TopNav";
import { FloatingActions } from "@/components/FloatingActions";
import { FeedbackFlow } from "@/components/FeedbackFlow";
import { SessionFeedbackGlobal } from "@/components/SessionFeedbackGlobal";
import { AtmosphericBackdrop } from "@/components/AtmosphericBackdrop";

export default function ShellLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden", position: "relative" }}>
      {/* Atmospheric orb layer — position: fixed behind everything. Only
          runs on signed-in app views; auth/onboarding have their own
          composition. */}
      <AtmosphericBackdrop />
      <a href="#main-content" className="skip-link">Skip to content</a>
      <TopNav />
      <main
        id="main-content"
        tabIndex={-1}
        style={{ flex: 1, overflowY: "auto", minWidth: 0, position: "relative", zIndex: 1 }}
      >
        {children}
      </main>
      <FloatingActions />
      <Suspense fallback={null}>
        <FeedbackFlow />
        <SessionFeedbackGlobal />
      </Suspense>
    </div>
  );
}
