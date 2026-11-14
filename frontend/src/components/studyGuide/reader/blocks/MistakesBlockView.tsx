import { Icon } from "@/components/Icon";
import type { MistakesBlock } from "@/lib/studyGuide/types";

import { BlockFrame } from "./BlockFrame";
import s from "./blocks.module.css";

/** Mistakes from the student's own quizzes, each with its fix. */
export function MistakesBlockView({ block }: { block: MistakesBlock }) {
  return (
    <BlockFrame blockId={block.id} tone="err" icon={<Icon name="error" size={15} />} label="Common mistakes" title={block.title}>
      <ol className={s.rows}>
        {block.mistakes.map((mistake, i) => (
          <li key={i} className={s.mistake}>
            <span className={`${s.badge} ${s.err}`}>{i + 1}</span>
            <div className={s.stack}>
              <strong>{mistake.title}</strong>
              <span className={s.dim}>{mistake.fix}</span>
              {mistake.evidence && <span className={s.small}>{mistake.evidence}</span>}
            </div>
          </li>
        ))}
      </ol>
    </BlockFrame>
  );
}
