import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Tooltip, InfoTip } from "./Tooltip";
import { Button } from "./Button";

// Tooltips open on hover or focus; each story focuses its trigger so the tip
// shows in the catalog and in the design-system export.
const focusTrigger = async ({ canvasElement }: { canvasElement: HTMLElement }) => {
  canvasElement.querySelector<HTMLElement>("button")?.focus();
  await new Promise((r) => setTimeout(r, 400));
};

const meta = {
  title: "UI/Tooltip",
  component: Tooltip,
  args: { content: "Mastery is how well you know this concept, from your quiz and tutor answers.", children: <Button>Hover me</Button> },
  argTypes: { placement: { control: "inline-radio", options: ["top", "bottom"] } },
  decorators: [(Story) => <div className="py-20"><Story /></div>],
  play: focusTrigger,
  parameters: {
    docs: {
      description: {
        component: "A short hint on hover or focus. Never put the only way to do something in a tooltip. `InfoTip` is the small (?) button that holds one.",
      },
    },
  },
} satisfies Meta<typeof Tooltip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Top: Story = {};
export const Bottom: Story = { args: { placement: "bottom" } };
export const Info: Story = {
  render: () => (
    <span className="flex items-center gap-1.5 text-md">
      Mastery <InfoTip content="How well you know this concept, from your quiz and tutor answers." />
    </span>
  ),
};
