"use client";
import React from "react";
import type { Components } from "react-markdown";

import type { Paragraph, ProseItem, Source } from "@/lib/studyGuide/types";

import { Markdown } from "./Markdown";
import s from "./reader.module.css";
import { useReader } from "./ReaderContext";
import { findSource, SOURCES_ANCHOR } from "./readerModel";

/** The paragraph's sources, as chips that jump to the Sources list. */
function Citations({ ids, sources }: { ids: string[]; sources: Source[] }) {
  return ids.map(id => {
    const source = findSource(sources, id);
    if (!source) return null;
    return (
      <a key={id} href={`#${SOURCES_ANCHOR}`} className={s.cite} aria-label={`Source: ${source.name}`}>
        {source.name}
      </a>
    );
  });
}

function ParagraphView({ paragraph, sources }: { paragraph: Paragraph; sources: Source[] }) {
  // The chips sit at the end of the paragraph's own line, so they are drawn
  // by the paragraph renderer. `**term**` is a key term: highlighted, not bold.
  const components = React.useMemo<Components>(
    () => ({
      p: ({ children }) => (
        <p className={s.paragraph}>
          {children} <Citations ids={paragraph.citations} sources={sources} />
        </p>
      ),
      strong: ({ children }) => <strong className={s.term}>{children}</strong>,
    }),
    [paragraph.citations, sources],
  );
  return <Markdown components={components}>{paragraph.text}</Markdown>;
}

/** A written passage. In Skim it is its one-line summary, or nothing. */
export function Prose({ item }: { item: ProseItem }) {
  const { mode, guide } = useReader();
  if (mode === "skim") {
    if (!item.summary) return null;
    return (
      <p className={s.skim} data-testid={`guide-skim-${item.id}`}>
        {item.summary}
      </p>
    );
  }
  return (
    <div className={s.prose} data-testid={`guide-prose-${item.id}`}>
      {item.paragraphs.map((paragraph, i) => (
        <ParagraphView key={i} paragraph={paragraph} sources={guide.content.sources} />
      ))}
    </div>
  );
}
