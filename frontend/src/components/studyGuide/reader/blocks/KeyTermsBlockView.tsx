import { Icon } from "@/components/Icon";
import type { KeyTermsBlock } from "@/lib/studyGuide/types";

import { BlockFrame } from "./BlockFrame";
import s from "./blocks.module.css";

export function KeyTermsBlockView({ block }: { block: KeyTermsBlock }) {
  return (
    <BlockFrame blockId={block.id} tone="amber" icon={<Icon name="file" size={15} />} label="Key terms" title={block.title}>
      <dl className={s.rows}>
        {block.terms.map((term, i) => (
          <div key={i} className={s.term}>
            <dt>{term.term}</dt>
            <dd>{term.definition}</dd>
          </div>
        ))}
      </dl>
    </BlockFrame>
  );
}
