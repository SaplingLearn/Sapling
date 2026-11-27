import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import React from "react";
import Dialog from "./Dialog";
import { Button } from "./ui/Button";

const DELETE_BODY = "Its notes, flashcards and quiz history go with it. This can't be undone.";

function DialogDemo({
  size = "md",
  title = "Delete this course?",
  body = DELETE_BODY,
  confirm = "Delete course",
  danger = true,
  dismissible = true,
}: {
  size?: "sm" | "md" | "lg" | "xl";
  title?: string;
  body?: string;
  confirm?: string;
  danger?: boolean;
  dismissible?: boolean;
}) {
  const [open, setOpen] = React.useState(true);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Open dialog</Button>
      <Dialog open={open} onClose={() => setOpen(false)} title={title} size={size} dismissible={dismissible}>
        <p className="text-md text-text-dim mb-4">{body}</p>
        <div className="flex justify-end gap-2">
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant={danger ? "danger" : "primary"} onClick={() => setOpen(false)}>{confirm}</Button>
        </div>
      </Dialog>
    </>
  );
}

const meta = {
  title: "Overlays/Dialog",
  component: DialogDemo,
  parameters: {
    layout: "fullscreen",
    docs: {
      description: {
        component:
          "A centred modal for a decision or a short form that blocks the page. Handles focus, Escape, the Tab trap and scroll lock. For a side panel use `Sheet`; for a read-mostly list use `PanelModal`; for a custom overlay build on `useOverlayBehaviour`. Never hand-build a `fixed inset-0` overlay.",
      },
    },
  },
} satisfies Meta<typeof DialogDemo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Confirm: Story = {};
export const Small: Story = { args: { size: "sm", title: "Sign out?", body: "You can sign back in with Google any time.", confirm: "Sign out", danger: false } };
export const Large: Story = {
  args: {
    size: "lg",
    title: "Import from Gradescope",
    body: "Sapling reads your course list and assignment grades. Your Gradescope password is never stored.",
    confirm: "Connect Gradescope",
    danger: false,
  },
};
export const NotDismissible: Story = {
  args: { dismissible: false, title: "Finish setting up", body: "Pick at least one course to continue.", confirm: "Choose courses", danger: false },
};
