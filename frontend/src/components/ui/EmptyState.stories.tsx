import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { EmptyState } from "./EmptyState";
import { Button } from "./Button";

const meta = {
  title: "UI/EmptyState",
  component: EmptyState,
  args: {
    title: "No flashcards yet",
    body: "Upload lecture notes and Sapling will make cards from the key ideas.",
    icon: "doc",
  },
  argTypes: { size: { control: "inline-radio", options: ["md", "hero"] } },
  decorators: [(Story) => <div className="w-140"><Story /></div>],
  parameters: {
    docs: {
      description: {
        component: "What a list or screen shows when it has nothing yet. Say what will appear and how to get it, with one action.",
      },
    },
  },
} satisfies Meta<typeof EmptyState>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const WithLinkAction: Story = { args: { action: { label: "Upload notes", href: "#" } } };
export const WithButtonAction: Story = { args: { action: <Button variant="primary">Upload notes</Button> } };
export const WithEyebrow: Story = { args: { eyebrow: "Flashcards" } };
export const Hero: Story = { args: { size: "hero", eyebrow: "Library", title: "Your library is empty", action: { label: "Add a course", href: "#" } } };
export const TitleOnly: Story = { args: { body: undefined, icon: undefined, title: "Nothing due today" } };
