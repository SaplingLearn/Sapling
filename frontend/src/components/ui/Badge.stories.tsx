import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Badge } from "./Badge";

const meta = {
  title: "UI/Badge",
  component: Badge,
  args: { children: "Rare", color: "var(--sap-500)" },
  parameters: {
    docs: {
      description: {
        component:
          "A pill tinted from one hue: rarity, role, grade. The hue goes on the border and a soft background; the text stays `--text` for contrast. Pass a token as `color`, never a hex. For status labels use `Chip`.",
      },
    },
  },
} satisfies Meta<typeof Badge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Neutral: Story = { args: { color: undefined, children: "Member" } };
export const Hues: Story = {
  render: () => (
    <div className="flex flex-wrap gap-2">
      <Badge color="var(--sap-500)">Common</Badge>
      <Badge color="var(--info)">Rare</Badge>
      <Badge color="var(--warn)">Epic</Badge>
      <Badge color="var(--err)">Legendary</Badge>
    </div>
  ),
};
