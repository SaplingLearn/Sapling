"use client";
/**
 * The reader for one study guide (/study/guide/[guideId]): a top bar with the
 * Read / Skim toggle, the guide itself on the page background, and a rail
 * with progress, the outline and the ask box.
 *
 * The guide is the contract in lib/studyGuide/types.ts. This screen loads it
 * (useGuide), follows its generation when it is still being written
 * (useGeneration), and draws it: prose passages and one component per block
 * type (blocks/). What it shows is derived in readerModel.ts.
 */
import React from "react";

import { useUser } from "@/context/UserContext";

import { ArticleSkeleton, GuideView } from "./GuideView";
import "./print.css";
import s from "./reader.module.css";
import type { ViewMode } from "./readerModel";
import { ReaderTopBar } from "./ReaderTopBar";
import { useGuide } from "./useGuide";

export function GuideReader({
  guideId,
  now,
}: {
  guideId: string;
  /** Test seam: a fixed "now" for the exam countdown. */
  now?: Date;
}) {
  const { userId } = useUser();
  const [mode, setMode] = React.useState<ViewMode>("read");
  const today = React.useMemo(() => now ?? new Date(), [now]);
  const { guide, error, update, toggleRead, save, sendFeedback } = useGuide(userId, guideId);

  return (
    // `data-guide-reader` is what print.css keys the app shell's print rules on.
    <div className={s.page} data-guide-reader="">
      <ReaderTopBar mode={mode} onMode={setMode} />
      {error ? (
        <p className={s.loadError} role="alert" data-testid="guide-load-error">
          {error}
        </p>
      ) : guide ? (
        <GuideView
          userId={userId}
          guide={guide}
          mode={mode}
          today={today}
          update={update}
          onToggleRead={toggleRead}
          onSave={save}
          onFeedback={sendFeedback}
        />
      ) : (
        <div className={s.shell}>
          <ArticleSkeleton />
        </div>
      )}
    </div>
  );
}
