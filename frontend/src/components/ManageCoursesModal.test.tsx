// @vitest-environment jsdom
/**
 * ManageCoursesModal add-flow tests (#360 review fixes):
 *   1. `already_existed: true` responses show an informational "Already taken
 *      in <term>" toast — NOT a false success toast (the no-retake rule fired,
 *      nothing was created).
 *   2. A created enrollment still gets the success toast.
 *   3. The Add button is disabled while the add request is in flight, so a
 *      double-click can't race two enrollments.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

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

function renderModal() {
  return render(
    <ToastProvider>
      <ManageCoursesModal
        open
        userId="u1"
        courses={[]}
        onClose={() => {}}
        onChanged={() => {}}
      />
    </ToastProvider>,
  );
}

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
