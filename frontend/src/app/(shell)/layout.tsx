import React, { Suspense } from "react";
import { Sidebar } from "@/components/Sidebar";
import { FloatingActions } from "@/components/FloatingActions";
import { FeedbackFlow } from "@/components/FeedbackFlow";
import { SessionFeedbackGlobal } from "@/components/SessionFeedbackGlobal";

export default function ShellLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      <a href="#main-content" className="skip-link">Skip to content</a>
      <Sidebar />
      <main
        id="main-content"
        tabIndex={-1}
        style={{ flex: 1, overflowY: "auto", minWidth: 0, position: "relative" }}
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
