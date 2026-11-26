import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { InlineBanner } from "./InlineBanner";
import { Button } from "./Button";

const meta = {
  title: "UI/InlineBanner",
  component: InlineBanner,
  args: { children: "You have 4 concepts due for review today." },
  argTypes: { tone: { control: "inline-radio", options: ["accent", "neutral"] } },
  decorators: [(Story) => <div className="w-140"><Story /></div>],
  parameters: {
    docs: {
      description: {
        component: "A one-line message inside the page, above the content it is about, with optional actions on the right. Not for errors that block the page.",
      },
    },
  },
} satisfies Meta<typeof InlineBanner>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Accent: Story = {};
export const Neutral: Story = { args: { tone: "neutral", children: "Your syllabus is still processing." } };
export const WithActions: Story = {
  args: {
    actions: (
      <>
        <Button size="sm">Start review</Button>
        <Button size="sm" variant="link">Later</Button>
      </>
    ),
  },
};
