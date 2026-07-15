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

/**
 * `100dvh`, not `100vh`: on iOS Safari `100vh` is the *large* viewport (the
 * height with the toolbar collapsed), so with the toolbar expanded a `100vh`
 * shell runs past the visual viewport and hides its own bottom edge — the
 * `/learn` composer, most visibly. Screens now fill `<main>` exactly (#331),
 * so there is no leftover scroll slack to drag that edge back into view.
 * `100dvh` tracks the visual viewport instead, and since the shell itself
 * never scrolls (`overflow: hidden`, inner panes scroll), the toolbar never
 * collapses and the value stays put — no resize thrash.
 */
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
          height: "100dvh",
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
          // The shell's scrollport: the root above is height:100dvh/overflow:hidden,
          // so this — not <body> — is what scrolls. `useScrollLock` targets it.
          data-scroll-container=""
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
        height: "100dvh",
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
        // The shell's scrollport — see the sidebar layout above.
        data-scroll-container=""
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
