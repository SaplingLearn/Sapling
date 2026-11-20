// @vitest-environment jsdom
/**
 * Component tests for DocumentUploadModal — covers the upload state machine
 * (#759): the row's terminal state is a function of uploadDocumentStream's
 * resolved UploadOutcome (one toast per failure, the server's message kept),
 * retry reuses the request_id, re-analyze starts clean, timeout vs cancel
 * aborts are told apart, and every close route aborts in-flight uploads and
 * fires onComplete when something was processed. Plus the request_id
 * "Reference:" line with a working "copy" button.
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
import { act, render, screen, waitFor, cleanup } from "@testing-library/react";
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
  type UploadOutcome,
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

const FAILED: UploadOutcome = {
  kind: "failed",
  message: "Could not read.",
  requestId: "trace-failed-1",
  afterResult: false,
};

const PROCESSED: UploadOutcome = {
  kind: "processed",
  documentId: "doc-1",
  result: {
    classification: { category: "lecture_notes" },
    summary: { abstract: "Fresh abstract." },
    concepts: { concepts: [{ name: "Backprop" }] },
  },
};

/** Mock one upload that never settles on its own; returns its signal. */
function hangUntilAborted() {
  const seen: { signal?: AbortSignal } = {};
  mockedUpload.mockImplementationOnce((_fd, _onEvent, signal) => {
    seen.signal = signal;
    return new Promise((_resolve, reject) => {
      signal?.addEventListener("abort", () =>
        reject(Object.assign(new Error("aborted"), { name: "AbortError" })),
      );
    });
  });
  return seen;
}

describe("DocumentUploadModal SSE error UX", () => {
  it("a typed server failure toasts ONCE and the row keeps the server's message (#759)", async () => {
    mockedUpload.mockImplementation(async (_fd, onEvent) => {
      onEvent({ type: "status", step: "start", message: "Document received." });
      onEvent({
        type: "error", step: "failed", message: "Could not read.",
        data: { request_id: "trace-failed-1" },
      });
      return FAILED;
    });

    const user = userEvent.setup();
    renderModal();
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));

    await waitFor(() => {
      expect(screen.getAllByText(/upload failed/i)).toHaveLength(1);
    });
    const row = screen.getByTestId("upload-modal-file-row-0");
    expect(row).toHaveTextContent("Could not read.");
    expect(row).not.toHaveTextContent(/ended without a result/i);
    expect(row).toHaveTextContent("error");
  });

  it("a failure AFTER the result leaves the row in error, not processed (#759)", async () => {
    mockedUpload.mockImplementation(async (_fd, onEvent) => {
      onEvent({ type: "result", step: "finalize", message: "ok", data: PROCESSED.result });
      onEvent({ type: "error", step: "failed", message: "processed but could not be saved" });
      return { kind: "failed", message: "processed but could not be saved", afterResult: true };
    });

    const user = userEvent.setup();
    renderModal();
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));

    const row = screen.getByTestId("upload-modal-file-row-0");
    await waitFor(() => expect(row).toHaveTextContent("could not be saved"));
    expect(row).not.toHaveTextContent("done");
    expect(screen.queryByTestId("upload-modal-file-reanalyze-0")).not.toBeInTheDocument();
    expect(screen.getByTestId("upload-modal-file-retry-0")).toBeInTheDocument();
    expect(screen.getAllByText(/upload failed/i)).toHaveLength(1);
  });

  it("retry of the same file to the same course reuses the request_id (#759)", async () => {
    mockedUpload.mockResolvedValue(FAILED);

    const user = userEvent.setup();
    renderModal();
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));

    const retryBtn = await screen.findByRole("button", { name: /retry/i });
    expect(mockedUpload).toHaveBeenCalledTimes(1);

    // uploadDocumentStream signature: (formData, onEvent, signal, requestId).
    const REQUEST_ID_ARG_INDEX = 3;
    const firstRequestId = mockedUpload.mock.calls[0][REQUEST_ID_ARG_INDEX];
    expect(typeof firstRequestId).toBe("string");

    await user.click(retryBtn);
    await waitFor(() => expect(mockedUpload).toHaveBeenCalledTimes(2));
    // The failed attempt's id came back on the error event; the retry sends
    // it again so a document the server DID save is replayed, not re-run.
    expect(mockedUpload.mock.calls[1][REQUEST_ID_ARG_INDEX]).toBe("trace-failed-1");
  });

  it("re-analyze mints a fresh request_id and clears the previous result (#759)", async () => {
    mockedUpload.mockResolvedValueOnce(PROCESSED);
    const pending = hangUntilAborted();

    const user = userEvent.setup();
    renderModal();
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));

    const row = screen.getByTestId("upload-modal-file-row-0");
    await waitFor(() => expect(row).toHaveTextContent("Fresh abstract."));
    expect(row).toHaveTextContent("Backprop");

    await user.click(screen.getByTestId("upload-modal-file-reanalyze-0"));
    await waitFor(() => expect(mockedUpload).toHaveBeenCalledTimes(2));
    expect(mockedUpload.mock.calls[1][3]).not.toBe(mockedUpload.mock.calls[0][3]);
    expect(row).not.toHaveTextContent("Fresh abstract.");
    expect(row).not.toHaveTextContent("Backprop");
    expect(pending.signal?.aborted).toBe(false);
  });

  it("surfaces request_id with a copy button on failed rows", async () => {
    const RID = "trace-failed-abc12345";
    mockedUpload.mockImplementation(async (_fd, onEvent) => {
      onEvent({ type: "error", step: "failed", message: "Could not read.", data: { request_id: RID } });
      return { kind: "failed", message: "Could not read.", requestId: RID, afterResult: false };
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

  it("a transport error (no typed outcome) still toasts once with its message", async () => {
    mockedUpload.mockRejectedValue(new Error("Network down"));

    const user = userEvent.setup();
    renderModal();
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));

    await waitFor(() => expect(screen.getAllByText(/upload failed/i)).toHaveLength(1));
    expect(screen.getByTestId("upload-modal-file-row-0")).toHaveTextContent("Network down");
  });
});

describe("DocumentUploadModal abort + close (#759)", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("the 4-minute timer aborts with the timeout message and no toast", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const pending = hangUntilAborted();

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderModal();
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));
    await waitFor(() => expect(pending.signal).toBeDefined());

    await act(async () => {
      vi.advanceTimersByTime(4 * 60 * 1000 + 1);
    });

    const row = screen.getByTestId("upload-modal-file-row-0");
    await waitFor(() => expect(row).toHaveTextContent(/longer than 4 minutes/));
    expect(row).toHaveTextContent("aborted");
    expect(screen.queryByText(/upload failed/i)).not.toBeInTheDocument();
  });

  it("closing with Cancel aborts in-flight uploads as a cancel, not a timeout", async () => {
    const pending = hangUntilAborted();
    const onClose = vi.fn();
    const onComplete = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const user = userEvent.setup();
    render(
      <ToastProvider>
        <DocumentUploadModal open userId="u1" courses={[COURSE]} onClose={onClose} onComplete={onComplete} />
      </ToastProvider>,
    );
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));
    await waitFor(() => expect(pending.signal).toBeDefined());

    await user.click(screen.getByTestId("upload-modal-cancel"));

    expect(pending.signal?.aborted).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(1);
    // Nothing was processed and no course was added: nothing to refresh.
    expect(onComplete).not.toHaveBeenCalled();
    expect(screen.queryByText(/longer than 4 minutes/)).not.toBeInTheDocument();
    expect(screen.queryByText(/upload failed/i)).not.toBeInTheDocument();
  });

  it.each([
    ["Cancel", "upload-modal-cancel"],
    ["X", "upload-modal-close"],
  ])("closing with %s after a processed upload fires onComplete", async (_label, testId) => {
    mockedUpload.mockResolvedValue(PROCESSED);
    const onClose = vi.fn();
    const onComplete = vi.fn();

    const user = userEvent.setup();
    render(
      <ToastProvider>
        <DocumentUploadModal open userId="u1" courses={[COURSE]} onClose={onClose} onComplete={onComplete} />
      </ToastProvider>,
    );
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));
    await waitFor(() =>
      expect(screen.getByTestId("upload-modal-file-row-0")).toHaveTextContent("done"),
    );

    await user.click(screen.getByTestId(testId));

    expect(onComplete).toHaveBeenCalledTimes(1);
    const uploaded = onComplete.mock.calls[0][0] as Array<{ docId?: string; status: string }>;
    expect(uploaded.map(u => [u.status, u.docId])).toEqual([["processed", "doc-1"]]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closing via the backdrop after a processed upload fires onComplete", async () => {
    mockedUpload.mockResolvedValue(PROCESSED);
    const onComplete = vi.fn();

    const user = userEvent.setup();
    render(
      <ToastProvider>
        <DocumentUploadModal open userId="u1" courses={[COURSE]} onClose={() => {}} onComplete={onComplete} />
      </ToastProvider>,
    );
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));
    await waitFor(() =>
      expect(screen.getByTestId("upload-modal-file-row-0")).toHaveTextContent("done"),
    );

    // The backdrop is the modal card's parent; the card stops propagation.
    await user.click(screen.getByTestId("upload-modal").parentElement as HTMLElement);
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("the parent closing the modal directly aborts in-flight uploads", async () => {
    const pending = hangUntilAborted();
    const user = userEvent.setup();
    const modal = (open: boolean) => (
      <ToastProvider>
        <DocumentUploadModal open={open} userId="u1" courses={[COURSE]} onClose={() => {}} onComplete={() => {}} />
      </ToastProvider>
    );
    const { rerender } = render(modal(true));
    await addFile(user);
    await user.click(screen.getByRole("button", { name: /start upload/i }));
    await waitFor(() => expect(pending.signal).toBeDefined());
    expect(pending.signal?.aborted).toBe(false);

    rerender(modal(false));

    expect(pending.signal?.aborted).toBe(true);
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

    await user.click(screen.getByRole("button", { name: /^Course\b/ }));
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
    expect(screen.getByRole("button", { name: /^Course\b/ })).toHaveTextContent("MATH200");
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
    await user.click(screen.getByRole("button", { name: /^Course\b/ }));
    expect(screen.getByRole("option", { name: /MATH200/ })).toBeInTheDocument();

    // Close (parent refreshes `courses` via onComplete in the real flow)
    // and reopen: the locally merged extras must be gone.
    rerender(modal(false));
    rerender(modal(true));

    await addFile(user);
    await user.click(screen.getByRole("button", { name: /^Course\b/ }));
    expect(screen.getByRole("option", { name: /CS101/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /MATH200/ })).not.toBeInTheDocument();
  });
});
