import { Icon } from "@/components/Icon";
import type { Source } from "@/lib/studyGuide/types";

import s from "./reader.module.css";
import { SOURCES_ANCHOR } from "./readerModel";

/** What the guide was made from. Every citation links here. */
export function Sources({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null;
  return (
    <section id={SOURCES_ANCHOR} data-testid="guide-sources" aria-label="Sources" className={s.sources}>
      <div className={s.sourcesHead}>
        <span className="label-micro">Made from {sources.length} of your materials</span>
        <span className={s.sourcesNote}>Every citation above links to one of these</span>
      </div>
      <ul className={s.sourceList}>
        {sources.map(source => (
          <li key={source.id}>
            <span className={s.sourceIcon} aria-hidden="true">
              <Icon name="file" size={14} />
            </span>
            <span className={s.sourceName}>{source.name}</span>
            <span className="label-micro">{source.kind}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
