// @vitest-environment jsdom
/** The sort menu from the keyboard. Picking with the mouse is in GuidesHome.test.tsx. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SortMenu } from "./SortMenu";

const item = (key: string) => screen.getByTestId(`guides-sort-${key}`);
const button = () => screen.getByTestId("guides-sort");

async function opened(onChange = vi.fn()) {
  const user = userEvent.setup();
  render(
    <>
      <SortMenu value="recent" onChange={onChange} />
      <button type="button">After the menu</button>
    </>,
  );
  await user.click(button());
  return { user, onChange };
}

afterEach(cleanup);

describe("the sort menu from the keyboard", () => {
  it("opens on its first item, moves with Down and Up, and picks with Enter", async () => {
    const { user, onChange } = await opened();
    expect(item("recent")).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(item("class")).toHaveFocus();
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(item("oldest")).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith("oldest");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(button()).toHaveFocus();
  });

  it("closes when Tab takes the focus out of it", async () => {
    const { user, onChange } = await opened();
    await user.keyboard("{ArrowUp}");
    await user.tab();
    expect(screen.getByRole("button", { name: "After the menu" })).toHaveFocus();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
});
