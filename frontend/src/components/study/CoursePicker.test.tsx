// @vitest-environment jsdom
/**
 * The Study pages' course field follows the listbox pattern CustomSelect does
 * (spec §13 A135): the open list takes focus with the chosen course active,
 * the arrows move, Enter picks, Escape closes, and both hand focus back to the
 * field.
 */
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";
import { ALL_COURSES, CoursePicker, listKey } from "./CoursePicker";

const course = (id: string, code: string, name: string) =>
  ({ course_id: id, course_code: code, course_name: name, color: "#123456" }) as unknown as EnrolledCourse;
const COURSES = [course("c1", "CS101", "Intro CS"), course("c2", "MATH210", "Linear Algebra"), course("c3", "BIO110", "Cell Bio")];

afterEach(cleanup);

function setup(value = "c2", allLabel?: string) {
  const onChange = vi.fn();
  render(<CoursePicker courses={COURSES} value={value} onChange={onChange} allLabel={allLabel} />);
  const field = screen.getByRole("button", { name: /^Course,/ });
  return { field, onChange };
}

const activeOption = () => {
  const list = screen.getByRole("listbox", { name: "Courses" });
  return document.getElementById(list.getAttribute("aria-activedescendant") ?? "");
};

describe("CoursePicker", () => {
  it("names the field by what it chooses and the current course", () => {
    const { field } = setup();
    expect(field.getAttribute("aria-label")).toBe("Course, MATH210 Linear Algebra");
  });

  it("opens from the keyboard with the list focused and the chosen course active", () => {
    const { field } = setup();
    field.focus();
    fireEvent.keyDown(field, { key: "Enter" });
    const list = screen.getByRole("listbox", { name: "Courses" });
    expect(document.activeElement).toBe(list);
    expect(activeOption()?.textContent).toContain("MATH210");
  });

  it("moves with the arrows, Home and End, and picks with Enter, handing focus back", () => {
    const { field, onChange } = setup();
    fireEvent.keyDown(field, { key: "ArrowDown" });
    const list = screen.getByRole("listbox", { name: "Courses" });
    fireEvent.keyDown(list, { key: "ArrowDown" });
    expect(activeOption()?.textContent).toContain("BIO110");
    fireEvent.keyDown(list, { key: "ArrowDown" }); // stays on the last
    expect(activeOption()?.textContent).toContain("BIO110");
    fireEvent.keyDown(list, { key: "Home" });
    expect(activeOption()?.textContent).toContain("CS101");
    fireEvent.keyDown(list, { key: "End" });
    fireEvent.keyDown(list, { key: "ArrowUp" });
    fireEvent.keyDown(list, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("c2");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(field);
  });

  it("closes on Escape without picking, and focus returns to the field", () => {
    const { field, onChange } = setup();
    fireEvent.click(field);
    const list = screen.getByRole("listbox", { name: "Courses" });
    fireEvent.keyDown(list, { key: "ArrowDown" });
    fireEvent.keyDown(list, { key: "Escape" });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(field);
  });

  it("a click on a course picks it and returns focus to the field", () => {
    const { field, onChange } = setup("c1", "All courses");
    fireEvent.click(field);
    fireEvent.click(screen.getByRole("option", { name: /All courses/ }));
    expect(onChange).toHaveBeenCalledWith(ALL_COURSES);
    expect(document.activeElement).toBe(field);
  });

  it("listKey maps each key to one step and ignores the rest", () => {
    expect(listKey("ArrowDown", 1, 3)).toEqual({ move: 2 });
    expect(listKey("ArrowUp", 0, 3)).toEqual({ move: 0 });
    expect(listKey("End", 0, 3)).toEqual({ move: 2 });
    expect(listKey(" ", 1, 3)).toEqual({ pick: true });
    expect(listKey("Tab", 1, 3)).toEqual({ close: "moveOn" });
    expect(listKey("a", 1, 3)).toBeNull();
  });
});
