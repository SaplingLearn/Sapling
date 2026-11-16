import type React from "react";

import type { Block } from "@/lib/studyGuide/types";

import { ChartBlockView } from "./ChartBlockView";
import { CheckBlockView } from "./CheckBlockView";
import { ComparisonBlockView } from "./ComparisonBlockView";
import { ConceptMapBlockView } from "./ConceptMapBlockView";
import { FormulaBlockView } from "./FormulaBlockView";
import { KeyTermsBlockView } from "./KeyTermsBlockView";
import { MistakesBlockView } from "./MistakesBlockView";
import { WorkedExampleBlockView } from "./WorkedExampleBlockView";

type BlockViews = { [T in Block["type"]]: React.ComponentType<{ block: Extract<Block, { type: T }> }> };

/** One component per block type. The type makes a missing one a compile error. */
export const BLOCK_VIEWS: BlockViews = {
  chart: ChartBlockView,
  mistakes: MistakesBlockView,
  formula: FormulaBlockView,
  worked_example: WorkedExampleBlockView,
  comparison: ComparisonBlockView,
  concept_map: ConceptMapBlockView,
  key_terms: KeyTermsBlockView,
  check: CheckBlockView,
};

/** A block of a type this build does not know (a newer server) is left out. */
export function BlockView({ block }: { block: Block }) {
  const View = BLOCK_VIEWS[block.type] as React.ComponentType<{ block: Block }> | undefined;
  return View ? <View block={block} /> : null;
}
