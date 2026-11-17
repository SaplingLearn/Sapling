import { Chip } from "@/components/ui";
import type { Depth, Goal } from "@/lib/studyGuide/types";

import { DEPTH_LABEL, GOAL_LABEL } from "./labels";

/** A guide's goal and depth as chips: the same on a home card and in the reader. */
export function GoalDepthChips({ goal, depth }: { goal: Goal; depth: Depth }) {
  return (
    <>
      <Chip variant="accent">{GOAL_LABEL[goal]}</Chip>
      <Chip>{DEPTH_LABEL[depth]}</Chip>
    </>
  );
}
