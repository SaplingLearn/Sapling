import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import React from "react";
import { PanelModal } from "./PanelModal";
import { Button } from "./Button";

const EVENTS = ["CS 330 lecture", "Office hours", "Problem set 6 due", "Study group", "Midterm review"];

function PanelDemo() {
  const [open, setOpen] = React.useState(true);
  return (
    <div className="p-6">
      <Button onClick={() => setOpen(true)}>Open panel</Button>
      {open && (
        <PanelModal label="Google Calendar events" onClose={() => setOpen(false)}>
          <ul className="flex flex-col divide-y divide-border">
            {EVENTS.map((e) => (
              <li key={e} className="py-3 px-4 text-md">{e}</li>
            ))}
          </ul>
        </PanelModal>
      )}
    </div>
  );
}

const meta = {
  title: "Overlays/PanelModal",
  component: PanelDemo,
  parameters: {
    layout: "fullscreen",
    docs: {
      description: {
        component: "A read-mostly modal: a sticky header with a label and Close, over a scrolling body. Rendered only while open.",
      },
    },
  },
} satisfies Meta<typeof PanelDemo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
