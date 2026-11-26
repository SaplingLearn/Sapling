"use client";
/**
 * Study Guides: every guide the student has made, as cards, and the way to a
 * new one.
 *
 * A card opens its guide in the reader (/study/guide/<id>), which also writes
 * a guide the New study guide dialog has just created.
 *
 * Saved keeps only the guides saved to the Library. `?saved=1` opens the home
 * with it on: the reader's "Saved to Library" leads here, since the rebuilt
 * Library (#717) lists documents only. The route wraps this page in Suspense
 * for `useSearchParams`.
 */
import React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { BackLink } from "@/components/BackLink";
import { AIDisclaimerChip } from "@/components/chat/AIDisclaimerChip";
import { TopBar } from "@/components/TopBar";
import { useUser } from "@/context/UserContext";
import type { EnrolledCourse } from "@/lib/api";
import type { GuideCard as Guide } from "@/lib/studyGuide/types";
import { SAVED_GUIDES_PARAM, editUrlInPlace, studyGuideReaderHref, studyHref } from "@/lib/toolHrefs";

import { classColor } from "../shared/classColor";
import { GuideCard } from "./GuideCard";
import { savedGuides, searchGuides, sortGuides, type SortKey } from "./guidesModel";
import { GuidesEmpty, GuidesLoadError, GuidesNoMatch, GuidesNoneSaved, GuidesSkeleton } from "./GuidesStates";
import { GuidesToolbar } from "./GuidesToolbar";
import s from "./home.module.css";
import { NewGuideModal } from "./NewGuideModal";
import { useGuides, type GuidesState } from "./useGuides";
import { useTermCourses } from "./useTermCourses";

export function GuidesHome({
  now,
}: {
  /** Test seam: a fixed "now" for the cards' dates. */
  now?: Date;
}) {
  const router = useRouter();
  const params = useSearchParams();
  const { userId } = useUser();
  const today = React.useMemo(() => now ?? new Date(), [now]);
  const list = useGuides(userId);
  const term = useTermCourses(userId);
  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState<SortKey>("recent");
  // Read once, on arrival. A render reads the router's params, never the live
  // URL: on a client-side navigation that is still the page being left.
  const [savedOnly, setSavedOnlyState] = React.useState(() => params.get(SAVED_GUIDES_PARAM) === "1");
  const [creating, setCreating] = React.useState(false);

  const shown = React.useMemo(
    () => sortGuides(searchGuides(savedOnly ? savedGuides(list.guides) : list.guides, query), sort),
    [list.guides, savedOnly, query, sort],
  );
  const openNew = () => setCreating(true);
  // The URL follows the toggle, with no navigation, so a reload keeps it.
  const setSavedOnly = (on: boolean) => {
    setSavedOnlyState(on);
    const url = new URL(window.location.href);
    if (on) url.searchParams.set(SAVED_GUIDES_PARAM, "1");
    else url.searchParams.delete(SAVED_GUIDES_PARAM);
    editUrlInPlace(url);
  };

  return (
    <div className={s.page}>
      <TopBar
        title="Study Guides"
        actions={<><AIDisclaimerChip /><BackLink href={studyHref()} label="Study" /></>}
      />
      {/* `tool-enter`: the Study tools' arrival fade (globals.css). */}
      <div className={`tool-enter ${s.home}`}>
        <GuidesToolbar
          query={query}
          onQuery={setQuery}
          sort={sort}
          onSort={setSort}
          savedOnly={savedOnly}
          onSavedOnly={setSavedOnly}
          onNew={openNew}
        />
        <GuidesContent
          list={list}
          shown={shown}
          query={query}
          savedOnly={savedOnly}
          now={today}
          enrolled={term.enrolled}
          onNew={openNew}
          onShowAll={() => setSavedOnly(false)}
        />
      </div>
      {creating && (
        <NewGuideModal
          userId={userId}
          courses={term.courses}
          coursesReady={term.ready}
          coursesFailed={term.failed}
          onRetryCourses={term.reload}
          semester={term.semester}
          onClose={() => setCreating(false)}
          onCreated={guideId => router.push(studyGuideReaderHref(guideId))}
          onCreatedLater={list.reload}
        />
      )}
    </div>
  );
}

/** Under the toolbar: the grid, or the one state that stands in for it. */
function GuidesContent({
  list, shown, query, savedOnly, now, enrolled, onNew, onShowAll,
}: {
  list: GuidesState;
  /** The guides Saved and the search keep, in the sort's order. */
  shown: Guide[];
  query: string;
  savedOnly: boolean;
  now: Date;
  /** The student's classes, for each card's class colour. */
  enrolled: EnrolledCourse[];
  onNew: () => void;
  /** Turns Saved off. */
  onShowAll: () => void;
}) {
  if (list.loading) return <GuidesSkeleton />;
  if (list.failed) return <GuidesLoadError onRetry={list.reload} />;
  if (list.guides.length === 0) return <GuidesEmpty onNew={onNew} />;
  if (savedOnly && savedGuides(list.guides).length === 0) return <GuidesNoneSaved onShowAll={onShowAll} />;
  if (shown.length === 0) return <GuidesNoMatch query={query} savedOnly={savedOnly} />;
  return (
    <ul
      className={s.grid}
      aria-label={savedOnly ? "Your saved study guides" : "Your study guides"}
      data-testid="guides-grid"
    >
      {shown.map(guide => (
        <GuideCard key={guide.id} guide={guide} now={now} color={classColor(enrolled, guide.course_id)} />
      ))}
    </ul>
  );
}
