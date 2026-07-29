// @vitest-environment jsdom
/**
 * ManageCoursesModal tests (#360 review fixes):
 *
 * Add flow:
 *   1. `already_existed: true` responses show an informational "Already taken
 *      in <term>" toast — NOT a false success toast (the no-retake rule fired,
 *      nothing was created).
 *   2. A created enrollment still gets the success toast.
 *   3. The Add button is disabled while the add request is in flight, so a
 *      double-click can't race two enrollments.
 *
 * Semester tabs (default = All semesters; scoping is opt-in):
 *   4. The "All semesters" tab renders and is active by default (empty stored
 *      value = unscoped).
 *   5. Clicking a term persists it (localStorage) and activates its tab.
 *   6. Clicking "All semesters" clears the stored value back to unscoped.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";
import { ACTIVE_SEMESTER_STORAGE_KEY } from "@/lib/useActiveSemester";

vi.mock("@/lib/api", () => ({
  addCourse: vi.fn(),
  deleteCourse: vi.fn(),
  updateCourseColor: vi.fn(),
  onboardingCoursesSearch: vi.fn(async () => ({
    courses: [{ id: "c-bio", course_code: "BIO-101", course_name: "Biology" }],
  })),
}));

import { ManageCoursesModal } from "./ManageCoursesModal";
import { ToastProvider } from "./ToastProvider";
import { addCourse } from "@/lib/api";

const mockedAddCourse = vi.mocked(addCourse);

function enrolled(code: string, term: string): EnrolledCourse {
  return {
    enrollment_id: `e-${code}`,
    course_id: `c-${code}`,
    course_code: code,
    course_name: code,
    school: "BU",
    department: "CS",
    color: null,
    nickname: null,
    node_count: 0,
    enrolled_at: "2025-08-25",
    term,
  };
}

function renderModal(courses: EnrolledCourse[] = []) {
  return render(
    <ToastProvider>
      <ManageCoursesModal
        open
        userId="u1"
        courses={courses}
        onClose={() => {}}
        onChanged={() => {}}
      />
    </ToastProvider>,
  );
}

const tab = (name: string) => screen.getByRole("button", { name });

/** The search results load behind a 200ms debounce; wait the Add button out. */
async function findAddButton() {
  return await screen.findByRole(
    "button",
    { name: /add/i },
    { timeout: 2000 },
  );
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ManageCoursesModal handleAdd", () => {
  it("shows an informational already-taken toast naming the term, not a success toast", async () => {
    mockedAddCourse.mockResolvedValue({
      course_id: "c-bio",
      already_existed: true,
      term: "Fall 2025",
    });

    renderModal();
    fireEvent.click(await findAddButton());

    await waitFor(() =>
      expect(screen.getByText("Already taken in Fall 2025")).toBeInTheDocument(),
    );
    expect(screen.queryByText(/^Added /)).toBeNull();
  });

  it("shows the success toast only when a row was created", async () => {
    mockedAddCourse.mockResolvedValue({
      course_id: "c-bio",
      already_existed: false,
    });

    renderModal();
    fireEvent.click(await findAddButton());

    await waitFor(() => expect(screen.getByText("Added BIO-101")).toBeInTheDocument());
    expect(screen.queryByText(/already taken/i)).toBeNull();
  });

  it("disables the Add button while the request is in flight", async () => {
    let release: (v: { course_id: string; already_existed: boolean }) => void;
    mockedAddCourse.mockImplementation(
      () => new Promise((resolve) => { release = resolve; }),
    );

    renderModal();
    const button = await findAddButton();
    fireEvent.click(button);

    await waitFor(() => expect(screen.getByText("Adding…")).toBeInTheDocument());
    expect((screen.getByText("Adding…") as HTMLButtonElement).disabled).toBe(true);
    // A second click while in flight must not fire another request.
    fireEvent.click(screen.getByText("Adding…"));
    expect(mockedAddCourse).toHaveBeenCalledTimes(1);

    release!({ course_id: "c-bio", already_existed: false });
    await waitFor(() => expect(screen.getByText("Added BIO-101")).toBeInTheDocument());
  });
});

describe("ManageCoursesModal semester tabs", () => {
  const courses = [enrolled("CS101", "Fall 2025"), enrolled("MATH210", "Spring 2026")];

  it("renders the All-semesters tab, active by default (empty stored value)", () => {
    renderModal(courses);

    expect(tab("All semesters")).toHaveAttribute("aria-pressed", "true");
    expect(tab("Fall 2025")).toHaveAttribute("aria-pressed", "false");
    expect(tab("Spring 2026")).toHaveAttribute("aria-pressed", "false");
    // All semesters → no term filter: both courses listed.
    expect(screen.getByText("Your courses")).toBeInTheDocument();
  });

  it("clicking a term persists it and activates its tab", () => {
    renderModal(courses);

    fireEvent.click(tab("Fall 2025"));

    expect(window.localStorage.getItem(ACTIVE_SEMESTER_STORAGE_KEY)).toBe("Fall 2025");
    expect(tab("Fall 2025")).toHaveAttribute("aria-pressed", "true");
    expect(tab("All semesters")).toHaveAttribute("aria-pressed", "false");
  });

  it("clicking All semesters clears the stored value back to unscoped", () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Spring 2026");
    renderModal(courses);

    expect(tab("Spring 2026")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(tab("All semesters"));

    expect(window.localStorage.getItem(ACTIVE_SEMESTER_STORAGE_KEY)).toBe("");
    expect(tab("All semesters")).toHaveAttribute("aria-pressed", "true");
    expect(tab("Spring 2026")).toHaveAttribute("aria-pressed", "false");
  });
});
