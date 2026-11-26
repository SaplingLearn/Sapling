import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import React from "react";
import { Switch } from "./Switch";

function SwitchDemo({ initial = false, disabled = false, label = "Email me a weekly summary" }: { initial?: boolean; disabled?: boolean; label?: string }) {
  const [on, setOn] = React.useState(initial);
  return (
    <div className="flex items-center gap-3">
      <Switch checked={on} onChange={setOn} label={label} disabled={disabled} />
      <span className="text-md">{label}</span>
    </div>
  );
}

const meta = {
  title: "UI/Switch",
  component: SwitchDemo,
  parameters: {
    docs: {
      description: {
        component: "An on/off setting that applies right away. `label` is the accessible name: name the setting, not the state.",
      },
    },
  },
} satisfies Meta<typeof SwitchDemo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Off: Story = {};
export const On: Story = { args: { initial: true } };
export const Disabled: Story = { args: { disabled: true } };
export const DisabledOn: Story = { args: { disabled: true, initial: true } };
