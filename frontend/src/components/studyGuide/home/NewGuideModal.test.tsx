// @vitest-environment jsdom
/**
 * The New study guide dialog: the class's scopes and materials, the choices,
 * the planned outline that follows them, and Generate.
 *
 * The pure rules behind it are pinned in newGuideModel.test.ts.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
// The upload dialog, reduced to what the tile needs of it: which class it was
// opened for, and a way to finish an upload.
vi.mock("@/components/DocumentUploadModal", () => ({
  DocumentUploadModal: (props: { open: boolean; courses: { course_id: string }[]; onClose: () => void; onComplete: (items: unknown[]) => void }) =>
    props.open ? (
      <div data-testid="upload-stub" data-courses={props.courses.map(c => c.course_id).join(",")}>
        <button type="button" data-testid="upload-stub-finish" onClick={() => { props.onComplete([]); props.onClose(); }}>Finish</button>
      </div>
    ) : null,
}));

import type { GuideOptions, GuidePlan, GuideRequest } from "@/lib/studyGuide/types";

import { NewGuideModal, type NewGuideModalProps } from "./NewGuideModal";
import { MAX_MATERIALS } from "./newGuideModel";
import { CS, MATH, OPTIONS, PLAN, deferred, material, mocks, resetMocks } from "./testKit";
import { PLAN_DEBOUNCE_MS } from "./usePlan";

const onClose = vi.fn();
const onCreated = vi.fn();

function renderModal(props: Partial<NewGuideModalProps> = {}) {
  return render(
    <NewGuideModal userId="u1" courses={[CS, MATH]} coursesReady coursesFailed={false} onRetryCourses={() => {}} semester="" onClose={onClose} onCreated={onCreated} {...props} />,
  );
}

/** The dialog with CS101's options in. */
async function modal(props: Partial<NewGuideModalProps> = {}) {
  renderModal(props);
  await screen.findByTestId("guide-new-materials-count");
  return userEvent.setup();
}

const tile = (id: string) => screen.getByTestId(`guide-new-material-${id}`);
/** The ids of the tiles that are on, in the list's order. */
const selected = () =>
  screen.getAllByTestId(/^guide-new-material-/)
    .filter(el => el.getAttribute("aria-pressed") === "true")
    .map(el => el.getAttribute("data-testid")?.replace("guide-new-material-", ""));
const planCalls = () => mocks.plan.mock.calls.length;
const lastPlanRequest = () => mocks.plan.mock.calls[planCalls() - 1][1];
/** Past the debounce, so a plan call that was going to happen has. */
const settle = () => new Promise(resolve => setTimeout(resolve, PLAN_DEBOUNCE_MS + 80));

async function pickScope(user: ReturnType<typeof userEvent.setup>, key: string) {
  await user.click(screen.getByTestId("guide-new-scope"));
  await user.click(screen.getByTestId(`guide-new-scope-option-${key}`));
}

/** The request the defaults make for CS101: whole course, all three lectures. */
const DEFAULT_REQUEST: GuideRequest = {
  course_id: "c1",
  semester: null,
  scope_kind: "course",
  scope_id: null,
  goal: "exam_prep",
  depth: "standard",
  material_ids: ["d1", "d2", "d3"],
  use_history: true,
};

beforeEach(() => {
  resetMocks();
  onClose.mockReset();
  onCreated.mockReset();
});
afterEach(cleanup);

describe("class and scope", () => {
  it("opens on the first class with its scopes loaded, the first one chosen", async () => {
    const user = await modal();
    expect(mocks.options).toHaveBeenCalledWith("u1", "c1", null);
    expect(screen.getByTestId("guide-new-class")).toHaveTextContent("CS101");
    expect(screen.getByTestId("guide-new-scope")).toHaveTextContent("Whole course");

    await user.click(screen.getByTestId("guide-new-scope"));
    const options = within(screen.getByRole("listbox")).getAllByRole("option").map(option => option.textContent);
    // The whole course, the exam with its due date, the assignment.
    expect(options).toEqual(["Whole courseWhole course✓", "Midterm 2Exam · due Sat, Nov 21", "Lab 5Assignment"]);
  });

  it("reads the options of the active term", async () => {
    await modal({ semester: "Fall 2026" });
    expect(mocks.options).toHaveBeenCalledWith("u1", "c1", "Fall 2026");
    await waitFor(() => expect(planCalls()).toBe(1));
    expect(lastPlanRequest().semester).toBe("Fall 2026");
  });

  it("loads the other class's scopes and materials when the class changes", async () => {
    const user = await modal();
    mocks.options.mockResolvedValue({
      scopes: [{ kind: "course", id: null, title: "Whole course", due_date: null, suggested_material_ids: ["m1"] }],
      materials: [material("m1", "Limits notes.pdf")],
    });
    await user.click(screen.getByTestId("guide-new-class"));
    await user.click(screen.getByTestId("guide-new-class-option-c2"));
    await screen.findByTestId("guide-new-material-m1");
    expect(mocks.options).toHaveBeenLastCalledWith("u1", "c2", null);
    expect(screen.queryByTestId("guide-new-material-d1")).toBeNull();
    expect(selected()).toEqual(["m1"]);
  });

  it("says a student with no class needs one first, and cannot generate", async () => {
    renderModal({ courses: [] });
    expect(await screen.findByText("Add a class first to make a guide.")).toBeTruthy();
    expect(screen.getByTestId("guide-new-class")).toBeDisabled();
    expect(screen.getByTestId("guide-new-generate")).toBeDisabled();
    expect(mocks.options).not.toHaveBeenCalled();
  });

  it("offers the options again when they could not be read", async () => {
    mocks.options.mockRejectedValueOnce(new Error("500"));
    renderModal();
    const retry = await screen.findByTestId("guide-new-options-retry");
    expect(screen.getByTestId("guide-new-generate")).toBeDisabled();
    await userEvent.setup().click(retry);
    await screen.findByTestId("guide-new-material-d1");
    expect(mocks.options).toHaveBeenCalledTimes(2);
  });
});

describe("goal and depth", () => {
  it("default to Exam prep and Standard, and pick one each", async () => {
    const user = await modal();
    const on = (id: string) => screen.getByTestId(id).getAttribute("aria-pressed");
    expect(on("guide-new-goal-exam_prep")).toBe("true");
    expect(on("guide-new-depth-standard")).toBe("true");
    await user.click(screen.getByTestId("guide-new-goal-practice"));
    await user.click(screen.getByTestId("guide-new-depth-cram"));
    expect(on("guide-new-goal-practice")).toBe("true");
    expect(on("guide-new-goal-exam_prep")).toBe("false");
    expect(on("guide-new-depth-cram")).toBe("true");
    expect(on("guide-new-depth-standard")).toBe("false");
  });

  it("are each a group named by its label, so a pressed option says what it is a choice of", async () => {
    await modal();
    const goal = screen.getByRole("group", { name: "Goal" });
    expect(goal).toBe(screen.getByTestId("guide-new-goal"));
    expect(within(goal).getAllByRole("button").map(button => button.textContent)).toEqual(["Practice", "Review", "Exam prep"]);
    const depth = screen.getByRole("group", { name: "Depth" });
    expect(depth).toBe(screen.getByTestId("guide-new-depth"));
    expect(within(depth).getByRole("button", { name: "Standard", pressed: true })).toBeTruthy();
  });
});

describe("materials", () => {
  it("lists each material with its category, the scope's suggested ones on", async () => {
    await modal();
    expect(tile("d3")).toHaveTextContent("Recursion slides.pptx");
    expect(tile("d3")).toHaveTextContent("slides");
    expect(tile("d1")).toHaveTextContent("lecture notes");
    expect(selected()).toEqual(["d1", "d2", "d3"]);
    expect(screen.getByTestId("guide-new-materials-count")).toHaveTextContent("3 of 3 selected");
  });

  it("re-applies the suggestion when the scope changes, over what was toggled", async () => {
    const user = await modal();
    await pickScope(user, "exam:e1");
    expect(selected()).toEqual(["d2", "d3"]);
    await user.click(tile("d1"));
    await user.click(tile("d3"));
    expect(selected()).toEqual(["d1", "d2"]);
    await pickScope(user, "assignment:a1");
    expect(selected()).toEqual(["d1"]);
    await pickScope(user, "exam:e1");
    expect(selected()).toEqual(["d2", "d3"]);
  });

  it("Suggested, All and None pick in one press", async () => {
    const user = await modal();
    await pickScope(user, "exam:e1");
    await user.click(screen.getByTestId("guide-new-materials-none"));
    expect(selected()).toEqual([]);
    expect(screen.getByTestId("guide-new-materials-count")).toHaveTextContent("0 of 3 selected");
    await user.click(screen.getByTestId("guide-new-materials-all"));
    expect(selected()).toEqual(["d1", "d2", "d3"]);
    await user.click(screen.getByTestId("guide-new-materials-suggested"));
    expect(selected()).toEqual(["d2", "d3"]);
  });

  it("stops at 30: past it a tile turns off but not on, and a note says why", async () => {
    // Listed oldest first, as the class sends them: d1 is the oldest.
    const materials = Array.from({ length: MAX_MATERIALS + 2 }, (_, i) => material(`d${i + 1}`));
    mocks.options.mockResolvedValue({
      scopes: [{ kind: "course", id: null, title: "Whole course", due_date: null, suggested_material_ids: [] }],
      materials,
    });
    const user = await modal();
    expect(screen.queryByTestId("guide-new-materials-cap")).toBeNull();

    // All takes the newest 30: the two oldest are what is left out.
    await user.click(screen.getByTestId("guide-new-materials-all"));
    expect(selected()).toEqual(materials.slice(2).map(m => m.id));
    expect(screen.getByTestId("guide-new-materials-cap")).toHaveTextContent("A guide uses up to 30 materials.");
    expect(tile("d1")).toHaveAttribute("aria-disabled", "true");
    await user.click(tile("d1"));
    expect(tile("d1")).toHaveAttribute("aria-pressed", "false");
    expect(selected()).toHaveLength(30);

    // One off makes room for one on.
    await user.click(tile("d32"));
    expect(screen.queryByTestId("guide-new-materials-cap")).toBeNull();
    await user.click(tile("d1"));
    expect(tile("d1")).toHaveAttribute("aria-pressed", "true");
    expect(selected()).toHaveLength(30);
    await waitFor(() => expect(lastPlanRequest().material_ids).toHaveLength(30));
  });

  it("a class with no materials says so, offers the upload, and cannot generate", async () => {
    mocks.options.mockResolvedValue({ scopes: OPTIONS.scopes, materials: [] });
    await modal();
    expect(screen.getByTestId("guide-new-materials-count")).toHaveTextContent("This class has none yet.");
    expect(screen.queryByTestId("guide-new-materials-all")).toBeNull();
    expect(screen.getByTestId("guide-new-upload")).toBeEnabled();
    expect(screen.getByTestId("guide-new-generate")).toBeDisabled();
    expect(screen.getByTestId("guide-new-outline")).toHaveTextContent("Pick at least one material");
  });

  it("the last tile uploads to this class, then selects what was added", async () => {
    const user = await modal();
    await pickScope(user, "exam:e1");
    expect(screen.queryByTestId("upload-stub")).toBeNull();
    await user.click(screen.getByTestId("guide-new-upload"));
    expect(screen.getByTestId("upload-stub")).toHaveAttribute("data-courses", "c1");

    const withNew: GuideOptions = { ...OPTIONS, materials: [...OPTIONS.materials, material("d4", "Lecture 4.pdf")] };
    mocks.options.mockResolvedValue(withNew);
    await user.click(screen.getByTestId("upload-stub-finish"));
    await screen.findByTestId("guide-new-material-d4");
    expect(mocks.options).toHaveBeenCalledTimes(2);
    // The scope's own picks are kept, the new document is added to them.
    expect(selected()).toEqual(["d2", "d3", "d4"]);
    expect(screen.getByTestId("guide-new-scope")).toHaveTextContent("Midterm 2");
    expect(screen.queryByTestId("upload-stub")).toBeNull();
  });
});

describe("quiz history", () => {
  it("is on by default, and the switch turns it off in the request", async () => {
    const user = await modal();
    const history = screen.getByRole("switch", { name: "Use my quiz history and mastery" });
    expect(history).toBe(screen.getByTestId("guide-new-history"));
    expect(history).toHaveAttribute("aria-checked", "true");
    await waitFor(() => expect(planCalls()).toBe(1));
    expect(lastPlanRequest().use_history).toBe(true);

    await user.click(history);
    expect(history).toHaveAttribute("aria-checked", "false");
    await waitFor(() => expect(planCalls()).toBe(2));
    expect(lastPlanRequest().use_history).toBe(false);
  });
});

describe("planned outline", () => {
  it("plans the choices and lists each section with its tier, share and the reading time", async () => {
    await modal();
    const outline = screen.getByTestId("guide-new-outline");
    const first = await within(outline).findByTestId("guide-new-outline-section-0");
    expect(mocks.plan).toHaveBeenCalledTimes(1);
    expect(mocks.plan).toHaveBeenCalledWith("u1", DEFAULT_REQUEST, expect.any(AbortSignal));
    expect(first).toHaveTextContent("Recursion");
    expect(first).toHaveTextContent("Struggling");
    expect(first).toHaveTextContent("60%");
    expect(first).toHaveAttribute("data-tier", "struggling");
    const second = screen.getByTestId("guide-new-outline-section-1");
    expect(second).toHaveTextContent("Loops");
    expect(second).toHaveTextContent("Learning");
    expect(second).toHaveTextContent("40%");
    expect(screen.queryByTestId("guide-new-outline-section-2")).toBeNull();
    expect(screen.getByTestId("guide-new-outline-minutes")).toHaveTextContent("about 12 min");
  });

  it("waits for the choices to rest: several quick changes are one call, with the last of them", async () => {
    await modal();
    await waitFor(() => expect(planCalls()).toBe(1));
    fireEvent.click(screen.getByTestId("guide-new-goal-practice"));
    fireEvent.click(screen.getByTestId("guide-new-depth-deep"));
    fireEvent.click(tile("d1"));
    expect(planCalls()).toBe(1);
    await waitFor(() => expect(planCalls()).toBe(2));
    expect(lastPlanRequest()).toEqual({ ...DEFAULT_REQUEST, goal: "practice", depth: "deep", material_ids: ["d2", "d3"] });
    await settle();
    expect(planCalls()).toBe(2);
  });

  it("follows the choices: a new plan replaces the old one", async () => {
    await modal();
    await screen.findByTestId("guide-new-outline-section-1");
    const cram: GuidePlan = { sections: [{ title: "Recursion", tier: "struggling", weight: 100 }], minutes: 4 };
    mocks.plan.mockResolvedValue(cram);
    fireEvent.click(screen.getByTestId("guide-new-depth-cram"));
    await waitFor(() => expect(screen.getByTestId("guide-new-outline-minutes")).toHaveTextContent("about 4 min"));
    expect(screen.getByTestId("guide-new-outline-section-0")).toHaveTextContent("100%");
    expect(screen.queryByTestId("guide-new-outline-section-1")).toBeNull();
  });

  it("never shows another class's outline while the new class's is planned", async () => {
    const user = await modal();
    await screen.findByTestId("guide-new-outline-section-0");
    const limits = deferred<GuidePlan>();
    mocks.options.mockResolvedValue({
      scopes: [{ kind: "course", id: null, title: "Whole course", due_date: null, suggested_material_ids: ["m1"] }],
      materials: [material("m1", "Limits notes.pdf")],
    });
    mocks.plan.mockReturnValue(limits.promise);
    await user.click(screen.getByTestId("guide-new-class"));
    await user.click(screen.getByTestId("guide-new-class-option-c2"));
    await screen.findByTestId("guide-new-material-m1");
    await waitFor(() => expect(lastPlanRequest().course_id).toBe("c2"));
    // CS101's sections are gone: the outline waits for Calculus's own.
    expect(screen.queryByTestId("guide-new-outline-section-0")).toBeNull();
    expect(screen.getByTestId("guide-new-outline")).toHaveAttribute("aria-busy", "true");

    await act(async () => limits.resolve({ sections: [{ title: "Limits", tier: "learning", weight: 100 }], minutes: 5 }));
    expect(await screen.findByTestId("guide-new-outline-section-0")).toHaveTextContent("Limits");
  });

  it("aborts the call before it, and a late answer to it is ignored", async () => {
    const slow = deferred<GuidePlan>();
    mocks.plan.mockReturnValueOnce(slow.promise);
    await modal();
    await waitFor(() => expect(planCalls()).toBe(1));
    const firstSignal = mocks.plan.mock.calls[0][2] as AbortSignal;
    expect(firstSignal.aborted).toBe(false);

    const review: GuidePlan = { sections: [{ title: "Loops", tier: "learning", weight: 100 }], minutes: 9 };
    mocks.plan.mockResolvedValue(review);
    fireEvent.click(screen.getByTestId("guide-new-goal-review"));
    expect(firstSignal.aborted).toBe(true);
    await waitFor(() => expect(screen.getByTestId("guide-new-outline-minutes")).toHaveTextContent("about 9 min"));

    slow.resolve(PLAN);
    await settle();
    expect(screen.getByTestId("guide-new-outline-minutes")).toHaveTextContent("about 9 min");
  });

  it("asks for a material when none is selected, and plans nothing", async () => {
    const user = await modal();
    await screen.findByTestId("guide-new-outline-section-0");
    await user.click(screen.getByTestId("guide-new-materials-none"));
    expect(screen.getByTestId("guide-new-outline")).toHaveTextContent("Pick at least one material to see the outline.");
    expect(screen.queryByTestId("guide-new-outline-section-0")).toBeNull();
    await settle();
    expect(planCalls()).toBe(1);
  });

  it("says so when the outline could not be planned, and still lets the guide be made", async () => {
    mocks.plan.mockRejectedValue(new Error("500"));
    await modal();
    await waitFor(() =>
      expect(screen.getByTestId("guide-new-outline")).toHaveTextContent("Couldn't plan the outline."));
    expect(screen.getByTestId("guide-new-generate")).toBeEnabled();
  });
});

describe("Generate guide", () => {
  it("is off until there is a class and at least one material", async () => {
    const user = await modal();
    const generate = screen.getByTestId("guide-new-generate");
    expect(generate).toBeEnabled();
    await user.click(screen.getByTestId("guide-new-materials-none"));
    expect(generate).toBeDisabled();
    await user.click(tile("d2"));
    expect(generate).toBeEnabled();
  });

  it("creates the guide from exactly the choices and hands its id on", async () => {
    const user = await modal();
    await pickScope(user, "exam:e1");
    await user.click(screen.getByTestId("guide-new-goal-review"));
    await user.click(screen.getByTestId("guide-new-depth-deep"));
    await user.click(tile("d1"));
    await user.click(screen.getByTestId("guide-new-history"));
    await user.click(screen.getByTestId("guide-new-generate"));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("g-new"));
    expect(mocks.create).toHaveBeenCalledTimes(1);
    expect(mocks.create).toHaveBeenCalledWith("u1", {
      course_id: "c1",
      semester: null,
      scope_kind: "exam",
      scope_id: "e1",
      goal: "review",
      depth: "deep",
      material_ids: ["d1", "d2", "d3"],
      use_history: false,
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("cannot be pressed twice while the guide is being created", async () => {
    const pending = deferred<{ id: string }>();
    mocks.create.mockReturnValue(pending.promise);
    const user = await modal();
    const generate = screen.getByTestId("guide-new-generate");
    await user.click(generate);
    expect(generate).toBeDisabled();
    expect(generate).toHaveTextContent("Starting…");
    pending.resolve({ id: "g-new" });
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("g-new"));
    expect(mocks.create).toHaveBeenCalledTimes(1);
  });

  it("a failure shows in the dialog and keeps every choice", async () => {
    mocks.create.mockRejectedValueOnce(new Error("500"));
    const user = await modal();
    await pickScope(user, "exam:e1");
    await user.click(screen.getByTestId("guide-new-goal-practice"));
    await user.click(screen.getByTestId("guide-new-generate"));

    const error = await screen.findByTestId("guide-new-error");
    expect(error).toHaveAttribute("role", "alert");
    expect(error).toHaveTextContent("Couldn't start the guide. Try again.");
    expect(onCreated).not.toHaveBeenCalled();
    expect(screen.getByTestId("guide-new-dialog")).toBeTruthy();
    expect(screen.getByTestId("guide-new-scope")).toHaveTextContent("Midterm 2");
    expect(screen.getByTestId("guide-new-goal-practice")).toHaveAttribute("aria-pressed", "true");
    expect(selected()).toEqual(["d2", "d3"]);

    // The same choices go through on the next try, and the error clears.
    await user.click(screen.getByTestId("guide-new-generate"));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("g-new"));
    expect(screen.queryByTestId("guide-new-error")).toBeNull();
    expect(mocks.create.mock.calls[1][1]).toEqual(mocks.create.mock.calls[0][1]);
  });

  it("Cancel closes without creating anything", async () => {
    const user = await modal();
    await user.click(screen.getByTestId("guide-new-cancel"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(mocks.create).not.toHaveBeenCalled();
  });
});
