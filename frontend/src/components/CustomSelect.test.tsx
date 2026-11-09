// @vitest-environment jsdom
/**
 * CustomSelect's keyboard and screen-reader contract (learning-loop spec §13
 * A135): the button is named by its label and the current choice; the open
 * list takes focus with the chosen (else first enabled) option active, exposed
 * as aria-activedescendant; arrows skip disabled options, Home / End jump,
 * Enter / Space choose and Escape cancels — both hand focus back to the button.
 */
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { CustomSelect } from "./CustomSelect";

afterEach(cleanup);

const OPTIONS = [
  { value: "cs", label: "CS 101" },
  { value: "math", label: "MATH 210", disabled: true },
  { value: "bio", label: "BIO 110" },
  { value: "eng", label: "ENG 150" },
];

function renderSelect(value = "bio", onChange = vi.fn()) {
  render(<CustomSelect ariaLabel="Course" value={value} options={OPTIONS} onChange={onChange} testId="pick" />);
  return { onChange, trigger: screen.getByTestId("pick") };
}

/** The label of the listbox's active option (its aria-activedescendant). */
const active = () => {
  const id = screen.getByRole("listbox").getAttribute("aria-activedescendant");
  return OPTIONS.find((o) => screen.getByRole("option", { name: o.label }).id === id)?.label ?? null;
};

describe("CustomSelect — keyboard and screen reader (spec §13 A135)", () => {
  it("names the button by its label and the current choice", () => {
    const { trigger } = renderSelect();
    expect(trigger).toHaveAccessibleName("Course BIO 110");
    expect(trigger).toHaveAttribute("aria-haspopup", "listbox");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("opens from the keyboard with focus on the list and the chosen option active", () => {
    const { trigger } = renderSelect();
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const list = screen.getByRole("listbox", { name: "Course" });
    expect(list).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-controls", list.id);
    expect(active()).toBe("BIO 110");
    expect(screen.getByRole("option", { name: "BIO 110" })).toHaveAttribute("aria-selected", "true");
  });

  it("starts on the first enabled option when nothing is chosen", () => {
    const { trigger } = renderSelect("none");
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(active()).toBe("CS 101");
  });

  it("moves with the arrows past disabled options, and Home / End jump to the ends", () => {
    const { trigger } = renderSelect("cs");
    fireEvent.keyDown(trigger, { key: " " });
    const list = screen.getByRole("listbox");
    fireEvent.keyDown(list, { key: "ArrowDown" });
    expect(active()).toBe("BIO 110"); // MATH 210 is disabled
    fireEvent.keyDown(list, { key: "ArrowUp" });
    expect(active()).toBe("CS 101");
    fireEvent.keyDown(list, { key: "End" });
    expect(active()).toBe("ENG 150");
    fireEvent.keyDown(list, { key: "Home" });
    expect(active()).toBe("CS 101");
    fireEvent.keyDown(list, { key: "ArrowUp" }); // wraps
    expect(active()).toBe("ENG 150");
  });

  it("Enter chooses, closes and hands focus back to the button", () => {
    const { trigger, onChange } = renderSelect();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "ArrowDown" });
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("eng");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("Space chooses too", () => {
    const { trigger, onChange } = renderSelect("cs");
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "End" });
    fireEvent.keyDown(screen.getByRole("listbox"), { key: " " });
    expect(onChange).toHaveBeenCalledWith("eng");
    expect(trigger).toHaveFocus();
  });

  it("Escape cancels: nothing chosen, focus back on the button", () => {
    const { trigger, onChange } = renderSelect();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "ArrowDown" });
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("a click on an option chooses it and hands focus back to the button", () => {
    const { trigger, onChange } = renderSelect();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("option", { name: "CS 101" }));
    expect(onChange).toHaveBeenCalledWith("cs");
    expect(trigger).toHaveFocus();
  });

  it("a disabled option cannot be chosen", () => {
    const { trigger, onChange } = renderSelect();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("option", { name: "MATH 210" }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("listbox")).toBeTruthy();
  });
});
