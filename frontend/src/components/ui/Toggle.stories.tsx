import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import React from "react";
import { Toggle } from "./Toggle";

type View = "week" | "month" | "term";
const OPTIONS: { value: View; label: string }[] = [
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "term", label: "Term" },
];

function ToggleDemo({ size, initial = "week" }: { size?: "sm" | "md"; initial?: View }) {
  const [value, setValue] = React.useState<View>(initial);
  return (
    <div className="flex flex-col gap-2">
      <span id="toggle-demo-label" className="label-micro">View</span>
      <Toggle options={OPTIONS} value={value} onChange={setValue} size={size} labelledBy="toggle-demo-label" />
    </div>
  );
}

const meta = {
  title: "UI/Toggle",
  component: ToggleDemo,
  parameters: {
    docs: {
      description: {
        component:
          "A row of pill buttons where one is pressed. Use for view switches and filters with a few options. For a form-style choice inside a panel use `SegmentedControl`; for an on/off setting use `Switch`.",
      },
    },
  },
} satisfies Meta<typeof ToggleDemo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Medium: Story = {};
export const Small: Story = { args: { size: "sm" } };
export const SecondSelected: Story = { args: { initial: "month" } };
