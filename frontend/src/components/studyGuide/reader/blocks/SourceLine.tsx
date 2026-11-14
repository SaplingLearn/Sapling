import type { Source } from "@/lib/studyGuide/types";

import { SOURCES_ANCHOR } from "../readerModel";

/** "Source: Lecture 7 slides", linked to the Sources list. */
export function SourceLine({ source }: { source: Source }) {
  return (
    <span>
      Source: <a href={`#${SOURCES_ANCHOR}`}>{source.name}</a>
    </span>
  );
}
