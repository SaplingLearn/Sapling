import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import React from "react";
import { FilterPills } from "./FilterPills";

type Filter = "all" | "due" | "mastered" | "struggling";

function FilterDemo() {
  const [value, setValue] = React.useState<Filter>("all");
  return (
    <FilterPills<Filter>
      options={[
        { value: "all", label: "All" },
        { value: "due", label: "Due", color: "var(--warn)" },
        { value: "mastered", label: "Mastered", color: "var(--sap-500)" },
        { value: "struggling", label: "Struggling", color: "var(--err)" },
      ]}
      value={value}
      onChange={setValue}
    />
  );
}

const meta = {
  title: "UI/FilterPills",
  component: FilterDemo,
  parameters: {
    docs: {
      description: { component: "Filter a list by one category, with an optional colour dot per option." },
    },
  },
} satisfies Meta<typeof FilterDemo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
