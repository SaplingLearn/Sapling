"use client";
import type { FormulaBlock } from "@/lib/studyGuide/types";

import { Markdown } from "../Markdown";
import { useReader } from "../ReaderContext";
import { findSource } from "../readerModel";
import { BlockFrame } from "./BlockFrame";
import s from "./blocks.module.css";
import { FormulaGlyph } from "./glyphs";
import { SourceLine } from "./SourceLine";

export function FormulaBlockView({ block }: { block: FormulaBlock }) {
  const { guide } = useReader();
  const source = findSource(guide.content.sources, block.source_id);
  return (
    <BlockFrame
      blockId={block.id}
      tone="accent"
      icon={<FormulaGlyph />}
      label="Formula"
      title={block.name}
      footer={source && <SourceLine source={source} />}
    >
      <div className={s.formula}>
        {/* Display math needs its fences on their own lines. */}
        <Markdown>{`$$\n${block.latex}\n$$`}</Markdown>
        <p className={s.spoken}>{block.spoken}</p>
      </div>
    </BlockFrame>
  );
}
