import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Chip } from "./Chip";
import { Icon } from "../Icon";

const meta = {
  title: "UI/Chip",
  component: Chip,
  args: { children: "Due Friday" },
  argTypes: { variant: { control: "inline-radio", options: ["neutral", "accent", "warn", "err", "info"] } },
  parameters: {
    docs: {
      description: {
        component:
          "Short status labels and tags. Pick the variant by meaning: `accent` good or active, `warn` needs attention, `err` failed, `info` neutral news. For a custom hue (rarity, role, grade) use `Badge`.",
      },
    },
  },
} satisfies Meta<typeof Chip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Neutral: Story = {};
export const Accent: Story = { args: { variant: "accent", children: "Mastered" } };
export const Warn: Story = { args: { variant: "warn", children: "Review due" } };
export const Err: Story = { args: { variant: "err", children: "Upload failed" } };
export const Info: Story = { args: { variant: "info", children: "New" } };
export const WithIcon: Story = { args: { variant: "accent", icon: <Icon name="check" size={12} />, children: "Synced" } };

export const AllVariants: Story = {
  render: () => (
    <div className="flex flex-wrap gap-2">
      <Chip>Neutral</Chip>
      <Chip variant="accent">Accent</Chip>
      <Chip variant="warn">Warn</Chip>
      <Chip variant="err">Error</Chip>
      <Chip variant="info">Info</Chip>
    </div>
  ),
};
