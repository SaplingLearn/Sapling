import type { ComparisonBlock } from "@/lib/studyGuide/types";

import { BlockFrame } from "./BlockFrame";
import s from "./blocks.module.css";
import { TableGlyph } from "./glyphs";

/** A small table. The emphasised row is the one exams ask about most. */
export function ComparisonBlockView({ block }: { block: ComparisonBlock }) {
  return (
    <BlockFrame blockId={block.id} tone="plum" icon={<TableGlyph />} label="Comparison" title={block.title}>
      <div className={s.tableWrap}>
        <table className={s.table}>
          <thead>
            <tr>
              <td />
              {block.columns.map((column, i) => (
                <th key={i} scope="col">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, i) => (
              <tr key={i} className={row.emphasis ? s.emphasis : undefined}>
                <th scope="row">
                  {row.label}
                  {row.emphasis && <span className={s.tested}>Most tested</span>}
                </th>
                {row.cells.map((cell, j) => (
                  <td key={j}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </BlockFrame>
  );
}
