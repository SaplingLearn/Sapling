import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { AnswerOption } from "./AnswerOption";

const meta = {
  title: "UI/AnswerOption",
  component: AnswerOption,
  args: { letter: "B", text: "The derivative of the outer function times the derivative of the inner function", state: "default" },
  argTypes: { state: { control: "inline-radio", options: ["default", "selected", "correct", "chosen-wrong", "muted"] } },
  decorators: [(Story) => <div role="radiogroup" aria-label="Answer" className="w-120"><Story /></div>],
  parameters: {
    docs: {
      description: {
        component:
          "One multiple-choice answer row. Lives inside a `role=\"radiogroup\"` that owns the roving tab stop. After marking, the chosen row shows `status`.",
      },
    },
  },
} satisfies Meta<typeof AnswerOption>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Selected: Story = { args: { state: "selected" } };
export const Correct: Story = { args: { state: "correct", checked: true, status: "Correct" } };
export const ChosenWrong: Story = { args: { state: "chosen-wrong", status: "Incorrect" } };
export const Muted: Story = { args: { state: "muted" } };
export const Disabled: Story = { args: { disabled: true } };

export const MarkedQuestion: Story = {
  render: () => (
    <div className="flex flex-col gap-2">
      <AnswerOption letter="A" text="Add the two derivatives" state="muted" />
      <AnswerOption letter="B" text="Outer derivative times inner derivative" state="correct" />
      <AnswerOption letter="C" text="Multiply the two functions first" state="chosen-wrong" status="Incorrect" />
      <AnswerOption letter="D" text="Only differentiate the inner function" state="muted" />
    </div>
  ),
};
