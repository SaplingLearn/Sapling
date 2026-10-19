// @vitest-environment jsdom
/**
 * Component tests for DocumentUploadModal — covers SSE-driven error UX:
 *   1. Terminal error event (`step="failed"`) -> toast.error
 *      (the only error step since #151b — `step="fallback"` died with the
 *      legacy pipeline)
 *   2. Retry button mints a fresh request_id on the second uploadDocumentStream call
 *   3. request_id is surfaced under the row with a working "copy" button
 *
 * Plus the inline course-add flow (#186): a course added via the modal's
 * search must be immediately selectable in the per-file Course dropdown,
 * default new rows for zero-course users, and reset when the modal reopens.
 *
 * The module-level vi.mock for "@/lib/api" replaces the real network helpers
 * with controllable spies so tests can drive arbitrary SSE event sequences.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, waitFor, within, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Hoisted mock module: vitest evaluates the vi.mock factory before imports,
// but referencing top-level vars inside it is forbidden. Defining the spies
// inside the factory and re-importing them below keeps everything in scope.
vi.mock("@/lib/api", () => {
  return {
    uploadDocumentStream: vi.fn(),
    updateDocumentCategory: vi.fn(),
    addCourse: vi.fn(),
    onboardingCoursesSearch: vi.fn(async () => ({ courses: [] })),
  };
});

import { DocumentUploadModal } from "./DocumentUploadModal";
import { ToastProvider } from "./ToastProvider";
import {
  uploadDocumentStream,
  addCourse,
  onboardingCoursesSearch,
  type UploadEvent,
  type EnrolledCourse,
  type OnboardingCourse,
} from "@/lib/api";

const mockedUpload = vi.mocked(uploadDocumentStream);
const mockedAddCourse = vi.mocked(addCourse);
const mockedSearch = vi.mocked(onboardingCoursesSearch);

const COURSE: EnrolledCourse = {
  enrollment_id: "e1",
  course_id: "c-1",
  course_code: "CS101",
  course_name: "Intro",
  school: "X",
  department: "CS",
  color: null,
  nickname: null,
  node_count: 0,
  enrolled_at: "2026-01-01",
  term: "Spring 2026",
};

function renderModal() {
  return render(
    <ToastProvider>
      <DocumentUploadModal
        open
        userId="u1"
        courses={[COURSE]}
        onClose={() => {}}
        onComplete={() => {}}
      />
    </ToastProvider>,
  );
}

/** Adds a fake PDF via the hidden <input type="file" /> the modal renders. */
async function addFile(user: ReturnType<typeof userEvent.setup>) {
  const file = new File(["%PDF-1.4 test"], "notes.pdf", {
    type: "application/pdf",
  });
  const input = document.querySelector(
    'input[type="file"]',
  ) as HTMLInputElement;
  await user.upload(input, file);
}

let clipboardWrite: ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockedUpload.mockReset();
  // jsdom 29 only exposes navigator.clipboard in secure contexts, so it's
  // undefined here by default. Inject a fresh stub via the Navigator
  // prototype (assigning to navigator.clipboard directly hits a getter-only
  // descriptor on the instance and throws).
  clipboardWrite = vi.fn(() => Promise.resolve());
  Object.defineProperty(window.Navigator.prototype, "clipboard", {
    configurable: true,
    get: () => ({ writeText: clipboardWrite }),
  });
});

afterEach(() => {
  // The modal renders via createPortal into document.body, and the toast
  // provider does the same. Default RTL cleanup unmounts the wrapper but
  // leaves siblings; do an explicit cleanup + clear portals so subsequent
  // tests don't see "multiple elements" matches.
  cleanup();
  document.body.innerHTML = "";
});

describe("DocumentUploadModal SSE error UX", () => {
  it("emits toast.error on terminal SSE error event (step=failed)", async () => {
    const events: UploadEvent[] = [
      { type: "status", step: "start", message: "Document received." },
      {
        type: "error",
        step: "failed",
        message: "Could not read.",
        data: { request_id: "trace-failed-1" },
      },
    ];
    mockedUpload.mockImplementation(async (_fd, onEvent) => {
      for (const e of events) onEvent(e);
      throw new Error("Upload stream ended without a result event.");
    });

    const user = userEvent.setup();
    renderModal();
    await addFile(user);

    await user.click(screen.getByRole("button", { name: /start upload/i }));

    // Two toasts fire on a terminal failure today: the in-band error
    // event handler runs `toast.error("Upload failed: …")`, and the
    // outer catch block then runs another after the stream rejects.
    // Pin that exact contract so a future de-dupe (or the opposite —
    // accidentally suppressing both) shows up as a test failure.
    await waitFor(() => {
      expect(screen.getAllByText(/upload failed/i).length).toBe(2);
    });
  });

  it("retry mints a fresh request_id on the second uploadDocumentStream call", async () => {
    const failureEvents: UploadEvent[] = [
      {
        type: "error",
        step: "failed",
        message: "Could not read.",
        data: { request_id: "trace-failed-1" },
      },
    ];
    mockedUpload.mockImplementation(async (_fd, onEvent) => {
      for (const e of failureEvents) onEvent(e);
      throw new Error("Upload stream ended without a result event.");
    });

    const user = userEvent.setup();
    renderModal();
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));

    // Wait for the first call to settle and the Retry button to render.
    const retryBtn = await screen.findByRole("button", { name: /retry/i });
    expect(mockedUpload).toHaveBeenCalledTimes(1);

    // uploadDocumentStream signature: (formData, onEvent, signal, requestId).
    // We're pinning the positional contract intentionally — if the call site
    // ever switches to a named-options object, update REQUEST_ID_ARG_INDEX
    // (and the matching call in lib/api.ts).
    const REQUEST_ID_ARG_INDEX = 3;
    const firstRequestId = mockedUpload.mock.calls[0][REQUEST_ID_ARG_INDEX];
    expect(typeof firstRequestId).toBe("string");
    expect((firstRequestId as string).length).toBeGreaterThan(0);

    await user.click(retryBtn);

    await waitFor(() => {
      expect(mockedUpload).toHaveBeenCalledTimes(2);
    });
    const secondRequestId = mockedUpload.mock.calls[1][REQUEST_ID_ARG_INDEX];
    expect(typeof secondRequestId).toBe("string");
    expect(secondRequestId).not.toBe(firstRequestId);
  });

  it("surfaces request_id with a copy button on failed rows", async () => {
    const RID = "trace-failed-abc12345";
    const events: UploadEvent[] = [
      {
        type: "error",
        step: "failed",
        message: "Could not read.",
        data: { request_id: RID },
      },
    ];
    mockedUpload.mockImplementation(async (_fd, onEvent) => {
      for (const e of events) onEvent(e);
      throw new Error("Upload stream ended without a result event.");
    });

    const user = userEvent.setup();
    renderModal();
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));

    // The Reference: line is keyed off status === "error" && requestId; wait for it.
    const ref = await screen.findByText(/reference:/i);
    // Modal shows a truncated form ("trace-fa…") — verify the rendered prefix.
    expect(ref).toHaveTextContent(/trace-fa/);

    // userEvent.setup() installs its own Clipboard stub directly on the
    // navigator instance, shadowing our prototype getter. Strip that and
    // re-install ours so the modal's writeText hits the spy.
    if (Object.prototype.hasOwnProperty.call(navigator, "clipboard")) {
      delete (navigator as unknown as { clipboard?: unknown }).clipboard;
    }
    Object.defineProperty(window.Navigator.prototype, "clipboard", {
      configurable: true,
      get: () => ({ writeText: clipboardWrite }),
    });

    const copyBtn = screen.getByRole("button", { name: /copy/i });
    await user.click(copyBtn);

    await waitFor(() => {
      expect(clipboardWrite).toHaveBeenCalledWith(RID);
    });
  });
});

describe("DocumentUploadModal inline course add (#186)", () => {
  const NEW_COURSE: OnboardingCourse = {
    id: "c-2",
    course_code: "MATH200",
    course_name: "Calculus II",
  };

  beforeEach(() => {
    mockedAddCourse.mockReset();
    mockedAddCourse.mockResolvedValue({ course_id: "c-2", already_existed: false });
    mockedSearch.mockReset();
    mockedSearch.mockResolvedValue({ courses: [NEW_COURSE] });
  });

  afterEach(() => {
    // Restore the hoisted-factory default so other describes see an empty
    // search result set regardless of test ordering.
    mockedSearch.mockReset();
    mockedSearch.mockImplementation(async () => ({ courses: [] }));
  });

  /** Searches for NEW_COURSE and clicks its result row, waiting for the add to settle. */
  async function inlineAddCourse(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByTestId("upload-modal-course-search"), "math");
    // The search is debounced 200ms; findBy* polls past it.
    const resultBtn = await screen.findByTestId(`upload-modal-course-result-${NEW_COURSE.id}`);
    await user.click(resultBtn);
    await waitFor(() => {
      expect(mockedAddCourse).toHaveBeenCalledWith("u1", NEW_COURSE.id);
      // addCourseInline clears the query + results once the add resolves.
      expect(
        screen.queryByTestId(`upload-modal-course-result-${NEW_COURSE.id}`),
      ).not.toBeInTheDocument();
    });
  }

  it("makes an inline-added course immediately selectable in the per-file Course dropdown", async () => {
    const user = userEvent.setup();
    renderModal();

    await inlineAddCourse(user);
    await addFile(user);

    await user.click(screen.getByRole("button", { name: "Course" }));
    // Both the enrolled course and the just-added one are options.
    expect(screen.getByRole("option", { name: /CS101/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /MATH200/ })).toBeInTheDocument();
  });

  it("defaults new file rows to the inline-added course when the user had no courses", async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <DocumentUploadModal
          open
          userId="u1"
          courses={[]}
          onClose={() => {}}
          onComplete={() => {}}
        />
      </ToastProvider>,
    );

    await inlineAddCourse(user);
    await addFile(user);

    // The row's course select defaults to the just-added course, not the
    // "Pick a course" placeholder (pre-#186 the default was courses[0] of
    // the stale prop, i.e. empty).
    expect(screen.getByRole("button", { name: "Course" })).toHaveTextContent("MATH200");
  });

  it("resets inline-added courses when the modal is closed and reopened", async () => {
    const user = userEvent.setup();
    const modal = (open: boolean) => (
      <ToastProvider>
        <DocumentUploadModal
          open={open}
          userId="u1"
          courses={[COURSE]}
          onClose={() => {}}
          onComplete={() => {}}
        />
      </ToastProvider>
    );
    const { rerender } = render(modal(true));

    await inlineAddCourse(user);
    await addFile(user);
    await user.click(screen.getByRole("button", { name: "Course" }));
    expect(screen.getByRole("option", { name: /MATH200/ })).toBeInTheDocument();

    // Close (parent refreshes `courses` via onComplete in the real flow)
    // and reopen: the locally merged extras must be gone.
    rerender(modal(false));
    rerender(modal(true));

    await addFile(user);
    await user.click(screen.getByRole("button", { name: "Course" }));
    expect(screen.getByRole("option", { name: /CS101/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /MATH200/ })).not.toBeInTheDocument();
  });
});

describe("DocumentUploadModal lifecycle (redesign prompt 03)", () => {
  /** A stream the test drives: emit events, then resolve, reject or abort. */
  function controllableStream() {
    const ctl: {
      emit: (e: UploadEvent) => void;
      finish: (doc: unknown) => void;
      signal?: AbortSignal;
    } = { emit: () => {}, finish: () => {} };
    mockedUpload.mockImplementation((_fd, onEvent, signal) => new Promise((resolve, reject) => {
      ctl.emit = onEvent;
      ctl.finish = resolve;
      ctl.signal = signal;
      signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));
    return ctl;
  }

  it("shows sending, then server processing stages, and only says Saved after the result", async () => {
    const ctl = controllableStream();
    const user = userEvent.setup();
    renderModal();
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));

    const row = screen.getByTestId("upload-modal-file-row-0");
    await waitFor(() => expect(row).toHaveTextContent("Sending…"));
    expect(screen.getByTestId("upload-modal-file-progress-0")).toHaveAttribute("data-phase", "sending");

    // Transport done: the server acknowledged the file but is still working.
    act(() => ctl.emit({ type: "status", step: "start", message: "Document received. Processing..." }));
    await waitFor(() => expect(row).toHaveTextContent("Processing…"));
    expect(row).not.toHaveTextContent("Saved");
    act(() => ctl.emit({ type: "progress", step: "classify", message: "Classifying document..." }));
    const bar = within(row).getByRole("progressbar");
    await waitFor(() => expect(bar).toHaveAttribute("aria-valuenow", "3"));
    expect(bar).toHaveAttribute("aria-valuetext", expect.stringMatching(/step 3 of 5: Classifying/));

    act(() => ctl.finish({ id: "doc-1", category: "lecture_notes", summary: "S", concept_notes: [] }));
    await waitFor(() => expect(row).toHaveTextContent("Saved"));
    expect(screen.queryByTestId("upload-modal-file-progress-0")).toBeNull();
    expect(screen.getByTestId("upload-modal-done")).toBeInTheDocument();
  });

  it("cancels one running upload, says what may still happen, and allows Retry", async () => {
    const ctl = controllableStream();
    const user = userEvent.setup();
    renderModal();
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));
    act(() => ctl.emit({ type: "status", step: "start", message: "Document received." }));

    await user.click(await screen.findByTestId("upload-modal-file-cancel-0"));
    expect(ctl.signal?.aborted).toBe(true);
    const err = await screen.findByTestId("upload-modal-file-error-0");
    expect(err).toHaveTextContent(/cancelled/i);
    expect(err).toHaveTextContent(/may still finish/i);
    expect(screen.getByTestId("upload-modal-file-row-0")).toHaveAttribute("data-status", "cancelled");
    expect(screen.getByTestId("upload-modal-file-retry-0")).toBeInTheDocument();
  });

  it("removes a queued file before start, and lists rejected files with their reason", async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderModal();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const big = new File(["x"], "huge.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 101 * 1024 * 1024 });
    await user.upload(input, [
      new File(["x"], "ok.pdf", { type: "application/pdf" }),
      new File(["x"], "photo.png", { type: "image/png" }),
      big,
    ]);
    const rejected = screen.getByTestId("upload-modal-rejected");
    expect(rejected).toHaveTextContent("photo.png: only PDF / DOCX / PPTX are accepted.");
    expect(rejected).toHaveTextContent("huge.pdf: exceeds the 100 MB limit.");
    expect(screen.getByTestId("upload-modal-file-row-0")).toHaveTextContent("ok.pdf");
    expect(screen.queryByTestId("upload-modal-file-row-1")).toBeNull();

    await user.click(screen.getByTestId("upload-modal-file-remove-0"));
    expect(screen.queryByTestId("upload-modal-file-row-0")).toBeNull();
    expect(mockedUpload).not.toHaveBeenCalled();
  });

  it("caps the queue at five files and names the extras", async () => {
    const user = userEvent.setup();
    renderModal();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, Array.from({ length: 6 }, (_, i) => new File(["x"], `f${i}.pdf`, { type: "application/pdf" })));
    expect(screen.getByTestId("upload-modal-file-row-4")).toBeInTheDocument();
    expect(screen.queryByTestId("upload-modal-file-row-5")).toBeNull();
    expect(screen.getByTestId("upload-modal-rejected")).toHaveTextContent("f5.pdf: not added: at most 5 files per upload.");
  });

  it("keeps successful files on partial failure and refreshes the library even when closed", async () => {
    mockedUpload
      .mockImplementationOnce(async () => ({ id: "doc-ok", category: "syllabus", summary: "ok" }))
      .mockImplementationOnce(async (_fd, onEvent) => {
        onEvent({ type: "error", step: "failed", message: "Could not read this document." });
        throw new Error("Upload stream ended without a result event.");
      });
    const onComplete = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <DocumentUploadModal open userId="u1" courses={[COURSE]} onClose={onClose} onComplete={onComplete} />
      </ToastProvider>,
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, [
      new File(["x"], "good.pdf", { type: "application/pdf" }),
      new File(["x"], "bad.pdf", { type: "application/pdf" }),
    ]);
    await user.click(screen.getByRole("button", { name: /start upload/i }));

    await waitFor(() => expect(screen.getByTestId("upload-modal-file-row-0")).toHaveAttribute("data-status", "processed"));
    await waitFor(() => expect(screen.getByTestId("upload-modal-file-row-1")).toHaveAttribute("data-status", "error"));
    // The server's own reason, not the client's generic stream error.
    expect(screen.getByTestId("upload-modal-file-error-1")).toHaveTextContent("Could not read this document.");
    expect(screen.getByTestId("upload-modal-summary")).toHaveTextContent("1 saved, 1 not saved");

    await user.click(screen.getByTestId("upload-modal-close"));
    expect(onComplete).toHaveBeenCalledTimes(1);
    const items = onComplete.mock.calls[0][0] as { status: string }[];
    expect(items.map((i) => i.status)).toEqual(["processed", "error"]);
    expect(onClose).toHaveBeenCalled();
  });

  it("explains that a course is needed when the learner has none", () => {
    render(
      <ToastProvider>
        <DocumentUploadModal open userId="u1" courses={[]} onClose={() => {}} onComplete={() => {}} />
      </ToastProvider>,
    );
    expect(screen.getByTestId("upload-modal-no-course")).toHaveTextContent(/add a course first/i);
  });
});
