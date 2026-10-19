// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { emptyOnboardingDraft, onboardingDraftKey, readOnboardingDraft, writeOnboardingDraft, academicChoices, type OnboardingDraft } from "./Onboarding.state";
import type { UploadItem } from "@/components/DocumentUploadModal";

const state = vi.hoisted(() => ({
  userId: "u1", completed: false,
  router: { push: vi.fn(), replace: vi.fn() },
  refreshProfile: vi.fn(async () => {}), signOut: vi.fn(async () => {}),
  uploads: {} as Record<string, (items: UploadItem[]) => void>,
}));
vi.mock("next/navigation", () => ({ useRouter: () => state.router }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: state.userId, userReady: true, isAuthenticated: true, refreshProfile: state.refreshProfile, signOut: state.signOut }) }));
vi.mock("@/lib/localSeed", () => ({ onboardingRedirect: vi.fn(async () => null) }));
vi.mock("@/components/Dialog", () => ({ default: ({ open, title, children }: { open: boolean; title: string; children: React.ReactNode }) => open ? <div role="dialog"><h2>{title}</h2>{children}</div> : null }));
vi.mock("@/components/DocumentUploadModal", () => ({ DocumentUploadModal: ({ open, onClose, userId, onComplete }: { open: boolean; userId: string; onClose: () => void; onComplete: (items: UploadItem[]) => void }) => {
  state.uploads[userId] = onComplete;
  return open ? <div role="dialog"><button data-testid="upload-modal-close" onClick={onClose}>Close upload</button></div> : null;
} }));
vi.mock("@/lib/api", () => ({ getMe: vi.fn(), getCourses: vi.fn(), getDocuments: vi.fn(), getGraph: vi.fn(), onboardingCoursesSearch: vi.fn(), submitOnboardingProfile: vi.fn(), deleteDocument: vi.fn() }));
import { deleteDocument, getMe, getCourses, getDocuments, getGraph, onboardingCoursesSearch, submitOnboardingProfile, type EnrolledCourse, type MeResponse } from "@/lib/api";
import { readOnboardingIntent } from "@/lib/onboardingHandoff";
import { Onboarding } from "./Onboarding";

const catalog = [{ id: "course-1", course_code: "CAS CS111", course_name: "Introduction to computer science" }, { id: "course-2", course_code: "CAS MA123", course_name: "Calculus I" }];
const enrolled = catalog.map((course, index) => ({ ...course, course_id: course.id, enrollment_id: `enrollment-${index}` })) as unknown as EnrolledCourse[];
const me = (): MeResponse => ({ user_id: state.userId, name: "Alex Rivera", onboarding_completed: state.completed, is_approved: true, username: null, avatar_url: "", roles: [], equipped_cosmetics: {}, is_admin: false });
const tickSearch = () => new Promise(resolve => setTimeout(resolve, 240));

function checkpoint(step: OnboardingDraft["step"], options: Partial<OnboardingDraft> = {}) {
  const d = { ...emptyOnboardingDraft(state.userId, "Alex Rivera"), step, year: "sophomore", majorsText: "Computer Science", courseIds: ["course-1"], courseCache: [catalog[0]], requiredSaved: step >= 3, goalCourseId: "course-1", ...options };
  writeOnboardingDraft(d);
  state.completed = d.requiredSaved;
  return d;
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear(); sessionStorage.clear();
  state.userId = "u1"; state.completed = false;
  state.uploads = {};
  vi.mocked(getMe).mockImplementation(async () => me());
  vi.mocked(getCourses).mockResolvedValue({ courses: enrolled });
  vi.mocked(getDocuments).mockResolvedValue({ documents: [] });
  vi.mocked(getGraph).mockResolvedValue({ nodes: [{ id: "root", course_id: "course-1", is_subject_root: true, concept_name: "Course" }, { id: "n1", course_id: "course-1", concept_name: "Functions" }, { id: "n2", course_id: "course-1", concept_name: "Recursion" }, { id: "other", course_id: "course-2", concept_name: "Limits" }], edges: [], stats: {} });
  vi.mocked(onboardingCoursesSearch).mockResolvedValue({ courses: catalog });
  vi.mocked(submitOnboardingProfile).mockImplementation(async () => { state.completed = true; return { user_id: state.userId, courses_linked: ["course-1"] }; });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("safe onboarding checkpoint", () => {
  it("never imports an unscoped draft or another account's goal", () => {
    localStorage.setItem("sapling_onboarding_draft", JSON.stringify({ first_name: "Wrong" }));
    checkpoint(4, { objective: "Private goal", goalTargets: ["n1"], goalScope: "concepts" });
    expect(readOnboardingDraft("u2")).toBeNull();
    expect(readOnboardingDraft("u1")?.objective).toBe("Private goal");
  });
  it("rejects malformed data, invalid years and too many goal targets", () => {
    const d = checkpoint(4);
    for (const patch of [{ step: 99 }, { year: "invented" }, { goalTargets: Array(13).fill("n") }, { objective: "x".repeat(501) }, { materials: [{ name: "file" }] }]) {
      localStorage.setItem(onboardingDraftKey("u1"), JSON.stringify({ ...d, ...patch }));
      expect(readOnboardingDraft("u1")).toBeNull();
    }
  });
  it("cannot use a pre-submit draft to skip required enrollment", () => {
    checkpoint(5, { requiredSaved: false });
    expect(readOnboardingDraft("u1")?.step).toBe(2);
    expect(academicChoices(" Computer Science, Mathematics,Computer Science, ")).toEqual(["Computer Science", "Mathematics"]);
  });
});

describe("six-step onboarding", () => {
  it("saves only required profile/course fields before optional setup and retains Back values", async () => {
    render(<Onboarding />);
    expect(await screen.findByLabelText("First name")).toHaveValue("Alex");
    fireEvent.click(screen.getByTestId("onboarding-continue"));
    expect(screen.getByTestId("onboarding-gate")).toHaveAttribute("data-step", "2");
    fireEvent.change(screen.getByTestId("onboarding-year"), { target: { value: "sophomore" } });
    fireEvent.change(screen.getByTestId("onboarding-chip-input-majors"), { target: { value: "Computer Science, Mathematics" } });
    fireEvent.click(screen.getByTestId("onboarding-back"));
    expect(screen.getByLabelText("First name")).toHaveValue("Alex");
    fireEvent.click(screen.getByTestId("onboarding-continue"));
    fireEvent.click(screen.getByTestId("onboarding-continue"));
    fireEvent.click(await screen.findByTestId("onboarding-course-result-course-1"));
    fireEvent.click(screen.getByTestId("onboarding-continue"));
    fireEvent.click(screen.getByTestId("onboarding-continue"));
    await screen.findByRole("heading", { name: "Bring your course materials." });
    expect(submitOnboardingProfile).toHaveBeenCalledTimes(1);
    expect(submitOnboardingProfile).toHaveBeenCalledWith({ user_id: "u1", first_name: "Alex", last_name: "Rivera", year: "sophomore", majors: ["Computer Science", "Mathematics"], minors: [], course_ids: ["course-1"] });
    expect(screen.getByText("Profile saved. Optional setup stays on this device.")).toBeVisible();
  });

  it("keeps choices and reports a partial course enrollment without claiming success", async () => {
    checkpoint(2, { courseIds: ["course-1", "course-2"], courseCache: catalog });
    vi.mocked(getCourses).mockResolvedValue({ courses: [enrolled[0]] });
    render(<Onboarding />);
    await screen.findByRole("heading", { name: "Connect your courses." });
    fireEvent.click(screen.getByTestId("onboarding-continue"));
    expect(await screen.findByTestId("onboarding-save-error")).toHaveTextContent("CAS MA123 could not be confirmed");
    expect(screen.getByTestId("onboarding-gate")).toHaveAttribute("data-step", "3");
    expect(readOnboardingDraft("u1")?.courseIds).toEqual(["course-1", "course-2"]);
    expect(state.router.push).not.toHaveBeenCalled();
  });

  it("reconciles a stale local saved flag against the actual account", async () => {
    checkpoint(5); state.completed = false;
    render(<Onboarding />);
    await screen.findByRole("heading", { name: "Connect your courses." });
    expect(readOnboardingDraft("u1")?.requiredSaved).toBe(false);
    expect(screen.queryByText("Start check-in")).not.toBeInTheDocument();
  });

  it("ignores a late catalog response and keeps selected courses across errors and retry", async () => {
    checkpoint(2);
    let resolveOld!: (value: { courses: typeof catalog }) => void;
    vi.mocked(onboardingCoursesSearch).mockImplementation(query => query === "old" ? new Promise(resolve => { resolveOld = resolve; }) : query === "new" ? Promise.resolve({ courses: [catalog[1]] }) : Promise.resolve({ courses: catalog }));
    render(<Onboarding />);
    const search = await screen.findByTestId("onboarding-course-search");
    fireEvent.change(search, { target: { value: "old" } });
    await act(async () => { await tickSearch(); });
    fireEvent.change(search, { target: { value: "new" } });
    await screen.findByTestId("onboarding-course-result-course-2");
    await act(async () => { resolveOld({ courses: [catalog[0]] }); });
    expect(screen.queryByTestId("onboarding-course-result-course-1")).not.toBeInTheDocument();
    expect(screen.getByTestId("onboarding-course-remove-CAS CS111")).toBeVisible();
    vi.mocked(onboardingCoursesSearch).mockRejectedValueOnce(new Error("offline"));
    fireEvent.change(search, { target: { value: "fail" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't search");
    fireEvent.click(screen.getByTestId("onboarding-recovery-retry"));
    await screen.findByTestId("onboarding-course-result-course-1");
    expect(readOnboardingDraft("u1")?.courseIds).toEqual(["course-1"]);
  });

  it("confirms actual selected concept IDs and objective only at explicit check-in", async () => {
    checkpoint(4);
    render(<Onboarding />);
    fireEvent.click(await screen.findByTestId("onboarding-goal-concept-scope"));
    fireEvent.click(await screen.findByTestId("onboarding-target-n1"));
    fireEvent.click(screen.getByTestId("onboarding-target-n2"));
    expect(screen.queryByTestId("onboarding-target-root")).not.toBeInTheDocument();
    expect(screen.queryByTestId("onboarding-target-other")).not.toBeInTheDocument();
    fireEvent.change(screen.getByTestId("onboarding-objective"), { target: { value: "Write recursive functions with confidence." } });
    fireEvent.click(screen.getByTestId("onboarding-continue"));
    await screen.findByRole("heading", { name: "Ready for your first check-in." });
    expect(readOnboardingIntent("u1", "course-1")).toBeNull();
    expect(submitOnboardingProfile).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("onboarding-continue"));
    expect(readOnboardingIntent("u1", "course-1")?.goal).toEqual({ text: "Write recursive functions with confidence.", target_node_ids: ["n1", "n2"] });
    expect(state.router.push).toHaveBeenCalledWith("/learn?course=course-1");
    expect(readOnboardingDraft("u1")?.handoffId).toBe(readOnboardingIntent("u1", "course-1")?.id);
  });

  it("offers whole-course exploration without concepts, and never implies an unused objective is applied", async () => {
    checkpoint(4);
    vi.mocked(getGraph).mockResolvedValue({ nodes: [], edges: [], stats: {} });
    render(<Onboarding />);
    const objective = await screen.findByTestId("onboarding-objective");
    expect(objective).toBeDisabled();
    await waitFor(() => expect(screen.getByTestId("onboarding-continue")).toBeEnabled());
    fireEvent.click(screen.getByTestId("onboarding-continue"));
    await screen.findByRole("heading", { name: "Ready for your first check-in." });
    fireEvent.click(screen.getByTestId("onboarding-continue"));
    expect(readOnboardingIntent("u1", "course-1")?.goal).toBeNull();
  });

  it("requires explicit concept selection and stops at twelve targets", async () => {
    checkpoint(4);
    vi.mocked(getGraph).mockResolvedValue({ nodes: Array.from({ length: 13 }, (_, i) => ({ id: `n${i}`, course_id: "course-1", concept_name: `Concept ${i}` })), edges: [], stats: {} });
    render(<Onboarding />);
    fireEvent.click(await screen.findByTestId("onboarding-goal-concept-scope"));
    await screen.findByTestId("onboarding-target-n0");
    expect(screen.getByTestId("onboarding-continue")).toBeDisabled();
    for (let i = 0; i < 12; i++) fireEvent.click(screen.getByTestId(`onboarding-target-n${i}`));
    expect(screen.getByTestId("onboarding-target-n12")).toBeDisabled();
    fireEvent.click(screen.getByTestId("onboarding-target-n0"));
    expect(screen.getByTestId("onboarding-target-n12")).toBeEnabled();
  });

  it("does not hydrate a cached account when the cookie identity differs", async () => {
    checkpoint(4, { objective: "Private goal" });
    vi.mocked(getMe).mockResolvedValue({ ...me(), user_id: "another-user" });
    render(<Onboarding />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Your account changed");
    expect(screen.queryByTestId("onboarding-objective")).not.toBeInTheDocument();
    expect(getGraph).not.toHaveBeenCalled();
  });

  it("resumes optional setup after refresh without saving the profile twice", async () => {
    checkpoint(3);
    const first = render(<Onboarding />);
    await screen.findByRole("heading", { name: "Bring your course materials." });
    fireEvent.click(screen.getByTestId("onboarding-skip-materials"));
    await screen.findByRole("heading", { name: "What would you like to work toward?" });
    first.unmount();
    render(<Onboarding />);
    await screen.findByRole("heading", { name: "What would you like to work toward?" });
    expect(readOnboardingDraft("u1")?.step).toBe(4);
    expect(submitOnboardingProfile).not.toHaveBeenCalled();
  });

  it("does not let a late identity response restore the previous account's setup", async () => {
    checkpoint(0, { firstName: "Private" });
    let finishOld!: (value: MeResponse) => void;
    vi.mocked(getMe).mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; }));
    const view = render(<Onboarding />);
    const oldMe = me();
    state.userId = "u2"; state.completed = false;
    view.rerender(<Onboarding />);
    expect(await screen.findByLabelText("First name")).toHaveValue("Alex");
    await act(async () => { finishOld(oldMe); });
    expect(screen.getByLabelText("First name")).toHaveValue("Alex");
    expect(readOnboardingDraft("u2")?.firstName).toBe("Alex");
    expect(readOnboardingDraft("u1")?.firstName).toBe("Private");
  });

  it("retains review and choices when session storage cannot hand off learning", async () => {
    checkpoint(5);
    render(<Onboarding />);
    await screen.findByRole("heading", { name: "Ready for your first check-in." });
    await waitFor(() => expect(getCourses).toHaveBeenCalled());
    const original = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
      if (this === sessionStorage) throw new Error("Blocked");
      original.call(this, key, value);
    });
    fireEvent.click(screen.getByTestId("onboarding-continue"));
    expect(screen.getByTestId("onboarding-save-error")).toHaveTextContent("couldn't keep this learning handoff");
    expect(state.router.push).not.toHaveBeenCalled();
    expect(readOnboardingDraft("u1")?.step).toBe(5);
  });

  it("cannot let a late material deletion overwrite a different account's materials", async () => {
    const oldFiles = [{ id: "old-1", name: "Private old notes.pdf", courseId: "course-1" }, { id: "old-2", name: "Another private old file.pdf", courseId: "course-1" }];
    const newFiles = [{ id: "new-1", name: "New account notes.pdf", courseId: "course-1" }];
    checkpoint(3, { materials: oldFiles });
    writeOnboardingDraft({ ...emptyOnboardingDraft("u2", "Second Student"), requiredSaved: true, courseIds: ["course-1"], courseCache: [catalog[0]], goalCourseId: "course-1", materials: newFiles, step: 3 });
    vi.mocked(getDocuments).mockImplementation(async user => ({ documents: (user === "u1" ? oldFiles : newFiles).map(file => ({ id: file.id, file_name: file.name, course_id: file.courseId })) }));
    let deleted!: (value: { deleted: boolean }) => void;
    vi.mocked(deleteDocument).mockReturnValue(new Promise(resolve => { deleted = resolve; }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const view = render(<Onboarding />);
    await screen.findByRole("heading", { name: "Bring your course materials." });
    await act(async () => {});
    fireEvent.click(screen.getByTestId("onboarding-delete-material-old-1"));
    expect(deleteDocument).toHaveBeenCalledWith("old-1", "u1");
    state.userId = "u2";
    view.rerender(<Onboarding />);
    await screen.findByText("New account notes.pdf");
    await act(async () => { deleted({ deleted: true }); });
    expect(screen.getByText("New account notes.pdf")).toBeVisible();
    expect(screen.queryByText("Another private old file.pdf")).not.toBeInTheDocument();
    expect(readOnboardingDraft("u2")?.materials.map(file => file.id)).toEqual(["new-1"]);
  });

  it("ignores an old account's upload callback after switching accounts", async () => {
    checkpoint(3);
    const view = render(<Onboarding />);
    await screen.findByRole("heading", { name: "Bring your course materials." });
    const oldUploadCallback = state.uploads.u1;
    state.userId = "u2"; state.completed = false;
    view.rerender(<Onboarding />);
    await screen.findByLabelText("First name");
    await act(async () => { oldUploadCallback([{ id: "upload-1", file: new File(["Private"], "Private old upload.pdf"), status: "processed", courseId: "course-1", docId: "private-doc" }]); });
    expect(readOnboardingDraft("u2")?.materials).toEqual([]);
    expect(screen.queryByText("Private old upload.pdf")).not.toBeInTheDocument();
  });

  it("distinguishes confirmed server profile saving from a failed local optional checkpoint", async () => {
    checkpoint(3);
    const original = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
      if (this === localStorage) throw new Error("Quota exceeded");
      original.call(this, key, value);
    });
    render(<Onboarding />);
    await screen.findByRole("heading", { name: "Bring your course materials." });
    expect(await screen.findByText("Profile saved. This browser couldn't save your setup draft; keep this tab open to finish.")).toBeVisible();
    expect(screen.queryByText("Profile saved. Optional setup stays on this device.")).not.toBeInTheDocument();
  });
});
