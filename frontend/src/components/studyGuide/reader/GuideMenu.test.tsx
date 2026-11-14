// @vitest-environment jsdom
/**
 * The three-dot menu from the keyboard: where the focus goes when it opens,
 * moves, closes, and when Save swaps the item under it.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { GuideMenu } from "./GuideMenu";

const item = (name: string) => screen.getByTestId(`guide-menu-${name}`);
const button = () => screen.getByTestId("guide-menu");

function menu(over: Partial<React.ComponentProps<typeof GuideMenu>> = {}) {
  return (
    <>
      <GuideMenu saved={false} busy={false} onSave={vi.fn()} onRegenerate={vi.fn()} {...over} />
      <button type="button">After the menu</button>
    </>
  );
}

async function opened(over: Partial<React.ComponentProps<typeof GuideMenu>> = {}) {
  const user = userEvent.setup();
  const view = render(menu(over));
  await user.click(button());
  return { user, ...view };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the guide menu from the keyboard", () => {
  it("opens with the focus on its first item, and Down and Up move through the items in a ring", async () => {
    const { user } = await opened();
    expect(item("save")).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(item("export")).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(item("regenerate")).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(item("save")).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(item("regenerate")).toHaveFocus();
  });

  it("passes over Regenerate while the guide is being written", async () => {
    const { user } = await opened({ busy: true });
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(item("save")).toHaveFocus();
  });

  it("gives the focus back to its button on Escape", async () => {
    const { user } = await opened();
    await user.keyboard("{ArrowDown}{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(button()).toHaveFocus();
  });

  it("closes when Tab takes the focus out of it", async () => {
    const { user } = await opened();
    await user.keyboard("{ArrowUp}");
    await user.tab();
    expect(screen.getByRole("button", { name: "After the menu" })).toHaveFocus();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(button()).toHaveAttribute("aria-expanded", "false");
  });

  it("moves the focus to Saved to Library when Save swaps the item under it", async () => {
    const onSave = vi.fn();
    const { user, rerender } = await opened({ onSave });
    await user.keyboard("{Enter}");
    expect(onSave).toHaveBeenCalledTimes(1);

    // The save went through: the item that had the focus is gone.
    rerender(menu({ saved: true, onSave }));
    expect(item("saved")).toHaveFocus();
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("gives the focus back to its button once an action is chosen", async () => {
    vi.stubGlobal("print", vi.fn());
    const { user } = await opened();
    await user.click(item("export"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(button()).toHaveFocus();
  });
});
