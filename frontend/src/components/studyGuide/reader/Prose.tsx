"use client";
import React from "react";
import type { Components } from "react-markdown";

import type { Paragraph, ProseItem, Source } from "@/lib/studyGuide/types";

import { Markdown } from "./Markdown";
import s from "./reader.module.css";
import { useReader } from "./ReaderContext";
import { findSource, isBlockMarkdown, SOURCES_ANCHOR } from "./readerModel";

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

/** `**term**` is a key term: highlighted, not bold. */
const Term: Components["strong"] = ({ children }) => <strong className={s.term}>{children}</strong>;

/** Block Markdown in the reader's own type: a code block, a list, text between them. */
const BLOCK_COMPONENTS: Components = {
  p: ({ children }) => <p className={s.paragraph}>{children}</p>,
  ul: ({ children }) => <ul className={s.list}>{children}</ul>,
  ol: ({ children }) => <ol className={s.list}>{children}</ol>,
  pre: ({ children }) => <pre className={s.code}>{children}</pre>,
  strong: Term,
};

/** One run of text. Its source chips sit at the end of its own last line. */
function TextParagraph({ paragraph, sources }: { paragraph: Paragraph; sources: Source[] }) {
  const components = React.useMemo<Components>(
    () => ({
      p: ({ children }) => (
        <p className={s.paragraph}>
          {children} <Citations ids={paragraph.citations} sources={sources} />
        </p>
      ),
      strong: Term,
    }),
    [paragraph.citations, sources],
  );
  return <Markdown components={components}>{paragraph.text}</Markdown>;
}

/** A code block or a list has no last line of text to end on: its chips go under it. */
function BlockParagraph({ paragraph, sources }: { paragraph: Paragraph; sources: Source[] }) {
  return (
    <div className={s.blockParagraph}>
      <Markdown components={BLOCK_COMPONENTS}>{paragraph.text}</Markdown>
      {paragraph.citations.length > 0 && (
        <p className={s.citeLine}>
          <Citations ids={paragraph.citations} sources={sources} />
        </p>
      )}
    </div>
  );
}

function ParagraphView({ paragraph, sources }: { paragraph: Paragraph; sources: Source[] }) {
  const View = isBlockMarkdown(paragraph.text) ? BlockParagraph : TextParagraph;
  return <View paragraph={paragraph} sources={sources} />;
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
