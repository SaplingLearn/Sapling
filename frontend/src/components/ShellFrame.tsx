"use client";

import React, { Suspense } from "react";
import { TopNav } from "./TopNav";
import { SideNav } from "./SideNav";
import { FloatingActions } from "./FloatingActions";
import { FeedbackFlow } from "./FeedbackFlow";
import { SessionFeedbackGlobal } from "./SessionFeedbackGlobal";
import { AtmosphericBackdrop } from "./AtmosphericBackdrop";
import { AchievementUnlockWatcher } from "./AchievementUnlockWatcher";
import { useLayoutPref } from "@/lib/useLayoutPref";
import { useIsMobile } from "@/lib/useIsMobile";

export function ShellFrame({ children }: { children: React.ReactNode }) {
  const [pref] = useLayoutPref();
  const isMobile = useIsMobile();
  const useSidebar = pref === "sidebar" && !isMobile;

  if (useSidebar) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          height: "100vh",
          overflow: "hidden",
          position: "relative",
        }}
      >
        <AtmosphericBackdrop />
        <a href="#main-content" className="skip-link">Skip to content</a>
        <SideNav />
        <main
          id="main-content"
          tabIndex={-1}
          style={{
            flex: 1,
            overflowY: "auto",
            minWidth: 0,
            position: "relative",
            zIndex: 1,
          }}
        >
          {children}
        </main>
        <FloatingActions />
        <Suspense fallback={null}>
          <FeedbackFlow />
          <SessionFeedbackGlobal />
        </Suspense>
        <AchievementUnlockWatcher />
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden",
        position: "relative",
      }}
    >
      <AtmosphericBackdrop />
      <a href="#main-content" className="skip-link">Skip to content</a>
      <TopNav />
      <main
        id="main-content"
        tabIndex={-1}
        style={{
          flex: 1,
          overflowY: "auto",
          minWidth: 0,
          position: "relative",
          zIndex: 1,
        }}
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
