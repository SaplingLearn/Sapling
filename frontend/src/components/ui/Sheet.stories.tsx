import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import React from "react";
import { Sheet } from "./Sheet";
import { Button } from "./Button";

function SheetDemo({ width = 480, title = "Ask about this question" }: { width?: number; title?: string }) {
  const [open, setOpen] = React.useState(true);
  return (
    <div className="p-6">
      <Button onClick={() => setOpen(true)}>Open sheet</Button>
      <Sheet open={open} onClose={() => setOpen(false)} title={title} width={width}>
        <div className="flex flex-col gap-3 text-md">
          <p>A side panel that keeps the page visible behind it. Use it for help, details or a secondary task.</p>
          <p className="text-text-dim">It closes on Escape, the close button or a click outside.</p>
        </div>
      </Sheet>
    </div>
  );
}

const meta = {
  title: "Overlays/Sheet",
  component: SheetDemo,
  parameters: {
    layout: "fullscreen",
    docs: {
      description: {
        component: "A panel that slides in from the right over the page. For a decision that blocks the page use `Dialog`.",
      },
    },
  },
} satisfies Meta<typeof SheetDemo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Wide: Story = { args: { width: 640, title: "Concept details" } };
