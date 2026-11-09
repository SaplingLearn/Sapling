// @vitest-environment jsdom
/** SyllabusUploadFlow step machine (#770): one run per dialog opening. */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const toast = vi.hoisted(() => ({
  show: vi.fn(), dismiss: vi.fn(), success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn(),
}));
const push = vi.hoisted(() => vi.fn());
vi.mock("@/components/ToastProvider", () => ({ useToast: () => toast }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", () => ({ uploadSyllabus: vi.fn(), applySyllabus: vi.fn(), getCourses: vi.fn() }));

import { SyllabusUploadFlow } from "./SyllabusUploadFlow";
import { applySyllabus, getCourses, uploadSyllabus } from "@/lib/api";

type UploadResult = Awaited<ReturnType<typeof uploadSyllabus>>;

const EXTRACTED = {
  id: "doc1", doc_id: "doc1",
  categories: [{ name: "Exams", weight: 100 }],
  assignments: [],
} as unknown as UploadResult;

beforeEach(() => {
  vi.mocked(getCourses).mockResolvedValue({
    courses: [{ course_id: "c1", course_code: "CS101", course_name: "Intro" }],
  } as never);
});

afterEach(() => { cleanup(); vi.resetAllMocks(); });

async function startUpload(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(await screen.findByRole("combobox"), await screen.findByRole("option", { name: /CS101/ }));
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  await user.upload(input, new File(["%PDF"], "syllabus.pdf", { type: "application/pdf" }));
}

describe("SyllabusUploadFlow", () => {
  it("never jumps a reopened dialog to review with the previous opening's upload", async () => {
    let resolveUpload!: (v: UploadResult) => void;
    vi.mocked(uploadSyllabus).mockImplementation(() => new Promise((r) => { resolveUpload = r; }));
    const user = userEvent.setup();
    const props = { userId: "u1", onClose: vi.fn() };
    const { rerender } = render(<SyllabusUploadFlow {...props} open />);
    await startUpload(user);
    expect(screen.getByText("Extracting syllabus…")).toBeInTheDocument();

    rerender(<SyllabusUploadFlow {...props} open={false} />);
    rerender(<SyllabusUploadFlow {...props} open />);
    await screen.findByRole("combobox");
    await act(async () => resolveUpload(EXTRACTED));

    expect(screen.queryByText("Categories")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("can cancel an upload, and a late answer is discarded", async () => {
    let resolveUpload!: (v: UploadResult) => void;
    vi.mocked(uploadSyllabus).mockImplementation(() => new Promise((r) => { resolveUpload = r; }));
    const user = userEvent.setup();
    render(<SyllabusUploadFlow open userId="u1" onClose={vi.fn()} />);
    await startUpload(user);
    await user.click(screen.getByRole("button", { name: "Cancel upload" }));
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    await act(async () => resolveUpload(EXTRACTED));
    expect(screen.queryByText("Categories")).not.toBeInTheDocument();
  });

  it("reports a failed course list instead of leaving an unhandled rejection", async () => {
    vi.mocked(getCourses).mockRejectedValue(Object.assign(new Error('{"detail":"Down."}'), { status: 503 }));
    render(<SyllabusUploadFlow open userId="u1" onClose={vi.fn()} />);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn't load your courses: Down."));
  });

  it("cannot be dismissed while the apply is saving", async () => {
    vi.mocked(uploadSyllabus).mockResolvedValue(EXTRACTED);
    vi.mocked(applySyllabus).mockImplementation(() => new Promise(() => {}));
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<SyllabusUploadFlow open userId="u1" onClose={onClose} />);
    await startUpload(user);
    await user.click(await screen.findByRole("button", { name: "Save to gradebook" }));
    expect(screen.getByText("Saving…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close dialog" })).not.toBeInTheDocument();
    screen.getByRole("dialog").focus();
    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
  });
});
