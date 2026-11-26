import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import React from "react";
import { SegmentedControl } from "./SegmentedControl";

function SegmentedDemo({ withDisabled = false }: { withDisabled?: boolean }) {
  const [value, setValue] = React.useState(10);
  return (
    <SegmentedControl
      ariaLabel="Number of questions"
      options={[
        { value: 5, label: "5" },
        { value: 10, label: "10" },
        { value: 20, label: "20", disabled: withDisabled },
      ]}
      value={value}
      onChange={setValue}
    />
  );
}

const meta = {
  title: "UI/SegmentedControl",
  component: SegmentedDemo,
  parameters: {
    docs: {
      description: {
        component:
          "One choice from a short fixed set inside a form or panel (a radio group with arrow-key movement). For a view switch in a toolbar use `Toggle`.",
      },
    },
  },
} satisfies Meta<typeof SegmentedDemo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const WithDisabledOption: Story = { args: { withDisabled: true } };
