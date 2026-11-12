"use client";
import { Toggle } from "@/components/ui";
import type { Depth, Goal } from "@/lib/studyGuide/types";

import { Field } from "./Field";
import { DEPTH_OPTIONS, GOAL_OPTIONS } from "./newGuideModel";

/** What the guide is for the student: practice, review or exam prep. */
export function GoalField({ value, onChange }: { value: Goal; onChange: (goal: Goal) => void }) {
  return (
    <Field label="Goal">
      <Toggle options={GOAL_OPTIONS} value={value} onChange={onChange} testid="guide-new-goal" />
    </Field>
  );
}

/** How much the guide writes: a cram sheet, a standard guide or a deep review. */
export function DepthField({ value, onChange }: { value: Depth; onChange: (depth: Depth) => void }) {
  return (
    <Field label="Depth">
      <Toggle options={DEPTH_OPTIONS} value={value} onChange={onChange} testid="guide-new-depth" />
    </Field>
  );
}
