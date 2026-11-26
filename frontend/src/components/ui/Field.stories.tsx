import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { fieldClass } from "./field";

function Fields({ disabled = false }: { disabled?: boolean }) {
  return (
    <form className="flex flex-col gap-3 w-90">
      <label className="flex flex-col gap-1.5 text-sm text-text-dim">
        Course name
        <input className={fieldClass} defaultValue="Algorithms" disabled={disabled} />
      </label>
      <label className="flex flex-col gap-1.5 text-sm text-text-dim">
        Term
        <select className={fieldClass} defaultValue="fall" disabled={disabled}>
          <option value="fall">Fall 2026</option>
          <option value="spring">Spring 2027</option>
        </select>
      </label>
      <label className="flex flex-col gap-1.5 text-sm text-text-dim">
        Notes
        <textarea className={fieldClass} rows={3} placeholder="Anything the tutor should know" disabled={disabled} />
      </label>
    </form>
  );
}

const meta = {
  title: "UI/Field",
  component: Fields,
  parameters: {
    docs: {
      description: {
        component: "`fieldClass` is the one text-field look for `<input>`, `<select>` and `<textarea>`. A real `Input` component is still to come.",
      },
    },
  },
} satisfies Meta<typeof Fields>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Disabled: Story = { args: { disabled: true } };
