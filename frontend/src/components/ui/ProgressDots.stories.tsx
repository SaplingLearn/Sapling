import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { ProgressDots } from "./ProgressDots";

const meta = {
  title: "UI/ProgressDots",
  component: ProgressDots,
  args: { total: 8, current: 3, answered: 3, ariaLabel: "Question progress", orientation: "row" },
  argTypes: { orientation: { control: "inline-radio", options: ["row", "column"] } },
  parameters: {
    docs: {
      description: {
        component:
          "Where the student is in a sequence of questions. `outcomes` colours marked dots; `onSelect` makes each dot a numbered button that jumps to its item.",
      },
    },
  },
} satisfies Meta<typeof ProgressDots>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Row: Story = {};
export const Column: Story = { args: { orientation: "column" } };
export const Start: Story = { args: { current: 0, answered: 0 } };
export const WithOutcomes: Story = { args: { current: 5, answered: 5, outcomes: [true, true, false, true, null] } };
export const Navigable: Story = { args: { onSelect: () => {} } };
export const NavigableDisabled: Story = { args: { onSelect: () => {}, disabled: true } };
