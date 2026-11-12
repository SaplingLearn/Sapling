"use client";

import React, { useId } from "react";

/**
 * A screen's heading, its line of help and any notice about it (a save that
 * sent the student back here). Onboarding moves focus to the heading each
 * time a screen arrives (`data-screen-heading`), and the heading names the
 * notice as its description, so both are read out together.
 */
export function ScreenHead({ title, sub, notice }: {
  title: React.ReactNode;
  sub?: React.ReactNode;
  notice?: React.ReactNode;
}) {
  const noticeId = useId();
  return (
    <>
      <h1 className="ob-h1" tabIndex={-1} data-screen-heading="" aria-describedby={notice ? noticeId : undefined}>
        {title}
      </h1>
      {sub && <p className="ob-sub">{sub}</p>}
      {notice && (
        <div id={noticeId} className="ob-notice" data-testid="onboarding-notice">
          {notice}
        </div>
      )}
    </>
  );
}
