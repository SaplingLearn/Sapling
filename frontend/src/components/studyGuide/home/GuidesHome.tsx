"use client";
/**
 * Study Guides: every guide the student has made, as cards, and the way to a
 * new one.
 *
 * A card opens its guide in the reader (/study/guide/<id>), which also writes
 * a guide the New study guide dialog has just created.
 */
import React from "react";
import { useRouter } from "next/navigation";

import { BackLink } from "@/components/BackLink";
import { AIDisclaimerChip } from "@/components/chat/AIDisclaimerChip";
import { TopBar } from "@/components/TopBar";
import { useUser } from "@/context/UserContext";
import type { EnrolledCourse } from "@/lib/api";
import type { GuideCard as Guide } from "@/lib/studyGuide/types";
import { studyGuideReaderHref, studyHref } from "@/lib/toolHrefs";

import { classColor } from "../shared/classColor";
import { GuideCard } from "./GuideCard";
import { searchGuides, sortGuides, type SortKey } from "./guidesModel";
import { GuidesEmpty, GuidesLoadError, GuidesNoMatch, GuidesSkeleton } from "./GuidesStates";
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
  const { userId } = useUser();
  const today = React.useMemo(() => now ?? new Date(), [now]);
  const list = useGuides(userId);
  const term = useTermCourses(userId);
  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState<SortKey>("recent");
  const [creating, setCreating] = React.useState(false);

  const shown = React.useMemo(
    () => sortGuides(searchGuides(list.guides, query), sort),
    [list.guides, query, sort],
  );
  const openNew = () => setCreating(true);

  return (
    <div className={s.page}>
      <TopBar
        title="Study Guides"
        actions={<><AIDisclaimerChip /><BackLink href={studyHref()} label="Study" /></>}
      />
      {/* `tool-enter`: the Study tools' arrival fade (globals.css). */}
      <div className={`tool-enter ${s.home}`}>
        <GuidesToolbar query={query} onQuery={setQuery} sort={sort} onSort={setSort} onNew={openNew} />
        <GuidesContent list={list} shown={shown} query={query} now={today} enrolled={term.enrolled} onNew={openNew} />
      </div>
      {creating && (
        <NewGuideModal
          userId={userId}
          courses={term.courses}
          coursesReady={term.ready}
          semester={term.semester}
          onClose={() => setCreating(false)}
          onCreated={guideId => router.push(studyGuideReaderHref(guideId))}
        />
      )}
    </div>
  );
}

/** Under the toolbar: the grid, or the one state that stands in for it. */
function GuidesContent({
  list, shown, query, now, enrolled, onNew,
}: {
  list: GuidesState;
  /** The guides the search keeps, in the sort's order. */
  shown: Guide[];
  query: string;
  now: Date;
  /** The student's classes, for each card's class colour. */
  enrolled: EnrolledCourse[];
  onNew: () => void;
}) {
  if (list.loading) return <GuidesSkeleton />;
  if (list.failed) return <GuidesLoadError onRetry={list.reload} />;
  if (list.guides.length === 0) return <GuidesEmpty onNew={onNew} />;
  if (shown.length === 0) return <GuidesNoMatch query={query} />;
  return (
    <ul className={s.grid} aria-label="Your study guides" data-testid="guides-grid">
      {shown.map(guide => (
        <GuideCard key={guide.id} guide={guide} now={now} color={classColor(enrolled, guide.course_id)} />
      ))}
    </ul>
  );
}
