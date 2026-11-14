"use client";
import React from "react";

import { Toggle } from "@/components/ui";
import type { Depth, Goal } from "@/lib/studyGuide/types";

import { Field } from "./Field";
import { DEPTH_OPTIONS, GOAL_OPTIONS } from "./newGuideModel";

/** What the guide is for the student: practice, review or exam prep. */
export function GoalField({ value, onChange }: { value: Goal; onChange: (goal: Goal) => void }) {
  const labelId = React.useId();
  return (
    <Field label="Goal" labelId={labelId}>
      <Toggle options={GOAL_OPTIONS} value={value} onChange={onChange} testid="guide-new-goal" labelledBy={labelId} />
    </Field>
  );
}

/** How much the guide writes: a cram sheet, a standard guide or a deep review. */
export function DepthField({ value, onChange }: { value: Depth; onChange: (depth: Depth) => void }) {
  const labelId = React.useId();
  return (
    <Field label="Depth" labelId={labelId}>
      <Toggle options={DEPTH_OPTIONS} value={value} onChange={onChange} testid="guide-new-depth" labelledBy={labelId} />
    </Field>
  );
}
