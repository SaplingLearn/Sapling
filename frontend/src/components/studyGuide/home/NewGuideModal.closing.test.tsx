// @vitest-environment jsdom
/**
 * The New study guide dialog around its edges: what the outline says before
 * the class has loaded, Escape with a list open, and closing the dialog while
 * the guide is being created.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/api", () => ({ getCourses: vi.fn() }));
vi.mock("@/lib/studyGuide/api", () => ({
  listGuides: vi.fn(),
  getGuideOptions: vi.fn(),
  planGuide: vi.fn(),
  createGuide: vi.fn(),
}));
vi.mock("@/components/DocumentUploadModal", () => ({ DocumentUploadModal: () => null }));

import type { GuideOptions } from "@/lib/studyGuide/types";

import { NewGuideModal } from "./NewGuideModal";
import { CS, MATH, OPTIONS, deferred, mocks, resetMocks } from "./testKit";

const onClose = vi.fn();
const onCreated = vi.fn();
const onCreatedLater = vi.fn();

const renderModal = () =>
  render(<NewGuideModal userId="u1" courses={[CS, MATH]} coursesReady coursesFailed={false} onRetryCourses={() => {}} semester="" onClose={onClose} onCreated={onCreated} onCreatedLater={onCreatedLater} />);

/** The dialog with CS101's options in. */
async function modal() {
  const view = renderModal();
  await screen.findByTestId("guide-new-materials-count");
  return { user: userEvent.setup(), ...view };
}

beforeEach(() => {
  resetMocks();
  onClose.mockReset();
  onCreated.mockReset();
  onCreatedLater.mockReset();
});
afterEach(cleanup);

describe("the planned outline before the class has loaded", () => {
  it("says it is loading, not that a material is missing", async () => {
    const options = deferred<GuideOptions>();
    mocks.options.mockReturnValue(options.promise);
    renderModal();
    const outline = await screen.findByTestId("guide-new-outline");
    expect(outline).toHaveTextContent("Loading this class's materials");
    expect(outline).not.toHaveTextContent("Pick at least one material");

    await act(async () => options.resolve(OPTIONS));
    expect(outline).not.toHaveTextContent("Loading this class's materials");
    expect(await screen.findByTestId("guide-new-outline-section-0")).toBeInTheDocument();
  });
});

describe("Escape", () => {
  for (const field of ["guide-new-class", "guide-new-scope"]) {
    it(`closes an open ${field} list and leaves the dialog open, then closes the dialog`, async () => {
      const { user } = await modal();
      const trigger = screen.getByTestId(field);
      await user.click(trigger);
      expect(screen.getByRole("listbox")).toBeInTheDocument();

      await user.keyboard("{Escape}");
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
      // The focus is back on the field, so the next key still reaches the dialog.
      expect(trigger).toHaveFocus();

      await user.keyboard("{Escape}");
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  }
});

describe("closing while the guide is being created", () => {
  it("does not open the reader once the dialog is gone", async () => {
    const created = deferred<{ id: string }>();
    mocks.create.mockReturnValue(created.promise);
    const { user, unmount } = await modal();
    await user.click(screen.getByTestId("guide-new-generate"));
    expect(mocks.create).toHaveBeenCalledTimes(1);

    // Cancel: the home takes the dialog away.
    await user.click(screen.getByTestId("guide-new-cancel"));
    expect(onClose).toHaveBeenCalledTimes(1);
    unmount();

    await act(async () => created.resolve({ id: "g-new" }));
    expect(onCreated).not.toHaveBeenCalled();
    // The row exists all the same: the home is told, so it can list it.
    expect(onCreatedLater).toHaveBeenCalledTimes(1);
  });

  it("tells the home nothing when that create fails", async () => {
    const created = deferred<{ id: string }>();
    mocks.create.mockReturnValue(created.promise);
    const { user, unmount } = await modal();
    await user.click(screen.getByTestId("guide-new-generate"));
    await user.click(screen.getByTestId("guide-new-cancel"));
    unmount();

    await act(async () => created.reject(new Error("500")));
    expect(onCreated).not.toHaveBeenCalled();
    expect(onCreatedLater).not.toHaveBeenCalled();
  });
});
