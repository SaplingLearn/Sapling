"use client";

/**
 * A document's next steps in the Library's details dialog (W8.1): the drafting
 * status line and the Tree / Quiz links from `libraryNext`, with this student's
 * flags. They lived in the old Library's detail panel; the dialog replaced it.
 */

import { useFlagMap } from "@/context/FlagsContext";
import { conceptIdsFromNotes, libraryNext } from "@/lib/libraryNext";
import { LEARNING_LOOP_FLAG } from "@/lib/learningLoopFlag";
import type { Document as Doc } from "@/lib/types";
import { useIsNavHidden } from "@/lib/useNavHidden";

import { LibraryNextCtas } from "./LibraryNextCtas";

export function LibraryDocNext({ doc }: { doc: Doc }) {
  const { flags } = useFlagMap();
  const isNavHidden = useIsNavHidden();
  const next = libraryNext({
    courseId: doc.course_id,
    conceptIds: conceptIdsFromNotes(doc.concept_notes),
    conceptCount: doc.concept_notes?.length ?? 0,
    checkItemsStatus: doc.check_items_status ?? null,
    loopOn: flags[LEARNING_LOOP_FLAG] === "on",
    treeHidden: isNavHidden("/tree"),
    quizHidden: isNavHidden("/quiz"),
  });
  return (
    <div style={{ padding: "0 4px" }}>
      <LibraryNextCtas next={next} />
    </div>
  );
}
