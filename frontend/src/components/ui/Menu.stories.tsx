import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import React from "react";
import { Menu, MenuTrigger, MenuContent, MenuItem, MenuSeparator, MenuRadioGroup, MenuRadioItem } from "./Menu";
import { Button } from "./Button";
import { Icon } from "../Icon";

function ActionsMenu({ open }: { open?: boolean }) {
  return (
    <Menu defaultOpen={open}>
      <MenuTrigger asChild>
        <Button>Actions</Button>
      </MenuTrigger>
      <MenuContent label="Course actions">
        <MenuItem><Icon name="pencil" size={14} />Rename</MenuItem>
        <MenuItem><Icon name="up" size={14} />Upload notes</MenuItem>
        <MenuItem disabled><Icon name="star" size={14} />Pin (coming soon)</MenuItem>
        <MenuSeparator />
        <MenuItem className="text-err"><Icon name="x" size={14} />Remove course</MenuItem>
      </MenuContent>
    </Menu>
  );
}

function SortMenu() {
  const [sort, setSort] = React.useState("recent");
  return (
    <Menu defaultOpen>
      <MenuTrigger asChild>
        <Button>Sort</Button>
      </MenuTrigger>
      <MenuContent label="Sort by">
        <MenuRadioGroup value={sort} onValueChange={setSort}>
          <MenuRadioItem value="recent" check={<Icon name="check" size={14} />}>Most recent</MenuRadioItem>
          <MenuRadioItem value="name" check={<Icon name="check" size={14} />}>Name</MenuRadioItem>
          <MenuRadioItem value="mastery" check={<Icon name="check" size={14} />}>Mastery</MenuRadioItem>
        </MenuRadioGroup>
      </MenuContent>
    </Menu>
  );
}

const meta = {
  title: "UI/Menu",
  component: ActionsMenu,
  decorators: [(Story) => <div className="min-h-75"><Story /></div>],
  parameters: {
    layout: "padded",
    docs: {
      description: {
        component:
          "A dropdown of actions or one choice (Radix DropdownMenu: arrow keys, typeahead, Escape, focus return). Never hand-build `role=\"menu\"`.",
      },
    },
  },
} satisfies Meta<typeof ActionsMenu>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Actions: Story = { args: { open: true } };
export const Closed: Story = { args: { open: false } };
export const RadioChoice: Story = { render: () => <SortMenu /> };
