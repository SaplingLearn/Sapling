import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Button } from "./Button";

const meta = {
  title: "UI/Button",
  component: Button,
  args: { children: "Save changes" },
  argTypes: {
    variant: { control: "inline-radio", options: ["primary", "secondary", "ghost", "danger", "link"] },
    size: { control: "inline-radio", options: ["sm", "md", "lg", "xl"] },
  },
  parameters: {
    docs: {
      description: {
        component:
          "Every action button. `secondary` is the default; `primary` for the one main action on a surface; `link` for text actions like Cancel or Done. Pills and segmented choices are `Toggle`, not Button.",
      },
    },
  },
} satisfies Meta<typeof Button>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Secondary: Story = {};
export const Primary: Story = { args: { variant: "primary" } };
export const Ghost: Story = { args: { variant: "ghost" } };
export const Danger: Story = { args: { variant: "danger", children: "Delete course" } };
export const Link: Story = { args: { variant: "link", children: "Cancel" } };
export const LinkPressed: Story = { args: { variant: "link", children: "Adjust", "aria-pressed": true } };
export const Disabled: Story = { args: { variant: "primary", disabled: true } };

export const Sizes: Story = {
  render: (args) => (
    <div className="flex items-center gap-3">
      <Button {...args} size="sm">Small</Button>
      <Button {...args} size="md">Medium</Button>
      <Button {...args} size="lg">Large</Button>
      <Button {...args} size="xl">Extra large</Button>
    </div>
  ),
  args: { variant: "primary" },
};
