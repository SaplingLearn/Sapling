// @vitest-environment jsdom
/**
 * Tab-switch interaction tests for FlashcardImportModal (#183).
 *
 * The five import tabs share ONE deck (`cards` state) via `setCards`, and the
 * modal mounts only the active tab. PasteTab's live re-parse effect used to
 * fire `onCards([])` on a bare mount (its local `text` starts empty), so
 * merely clicking back onto the Paste tab — the initial tab and the reset-to
 * tab on open — silently wiped a deck built on the Upload/URL/AI/Photo tabs.
 *
 *   1. Regression: build a deck via the (mocked) URL tab, click Paste —
 *      the deck must survive.
 *   2. Control: typing into Paste and then deleting all text still clears
 *      the deck — the intentional clear-by-deleting path keeps working.
 *   3. Control: after switching back to Paste, typing still re-parses and
 *      replaces the shared deck (the mount guard must not disable parsing).
 *
 * Real FlashcardImportModal + PasteTab + ParsedCardsTable + Dialog +
 * ToastProvider (the portal pattern proven in DocumentUploadModal.test.tsx);
 * the other tabs are mocked light, with the URL tab mock exposing a button
 * that injects a fixed deck. Assertions read the real commit button label
 * ("Import N cards") and the real ParsedCardsTable counter.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  importCommit: vi.fn(),
  importCloze: vi.fn(),
  importCleanup: vi.fn(),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1" }),
}));

// Deck injected by the mocked URL tab — the simplest non-paste channel into
// the shared `cards` state.
const URL_CARDS = vi.hoisted(() => [
  { front: "Mitochondria", back: "Powerhouse of the cell", row: 1 },
  { front: "Ribosome", back: "Protein synthesis", row: 2 },
]);

// A "slow fetch": the click captures the onCards the tab was rendered with,
// and the test delivers the reply later — after a tab switch / reopen (#769).
const slow = vi.hoisted(() => ({ deliver: null as null | ((next: unknown) => void) }));

vi.mock("./tabs/UrlTab", async () => {
  const { createElement, Fragment } = await import("react");
  return {
    UrlTab: ({ onCards }: { onCards: (next: typeof URL_CARDS) => void }) =>
      createElement(
        Fragment,
        null,
        createElement(
          "button",
          { type: "button", onClick: () => onCards(URL_CARDS) },
          "Inject mock deck",
        ),
        createElement(
          "button",
          { type: "button", onClick: () => { slow.deliver = onCards as (next: unknown) => void; } },
          "Start slow fetch",
        ),
      ),
  };
});
vi.mock("./tabs/UploadTab", () => ({ UploadTab: () => null }));
vi.mock("./tabs/AiTab", () => ({ AiTab: () => null }));
vi.mock("./tabs/PhotoTab", () => ({ PhotoTab: () => null }));

import { FlashcardImportModal } from "./FlashcardImportModal";
import { ToastProvider } from "../ToastProvider";

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

function modal(open = true, courses: EnrolledCourse[] = [COURSE]) {
  return (
    <ToastProvider>
      <FlashcardImportModal
        open={open}
        onClose={() => {}}
        courses={courses}
        documents={[]}
        onImported={() => {}}
      />
    </ToastProvider>
  );
}

function renderModal() {
  return render(modal());
}

// Accessible-name helpers. Tab buttons carry their bare label ("Paste",
// "URL"); the commit button's label doubles as the deck-size readout.
const tabButton = (label: string) => screen.getByRole("button", { name: label });
const importButton = (count: number) =>
  screen.getByRole("button", {
    name: `Import ${count} card${count === 1 ? "" : "s"}`,
  });

const pasteTextarea = () =>
  screen.getByPlaceholderText(/paste your cards here/i);

afterEach(() => {
  // UNMOUNT first, then sweep. Order matters and both steps are needed:
  //
  // - vitest.config.ts sets `globals: false`, so @testing-library/react does
  //   NOT auto-register its cleanup. Without an explicit call nothing here
  //   ever unmounted: React kept the tree — and its pending scheduler work —
  //   alive past the end of the file, and when jsdom was torn down that work
  //   landed on a `window` that no longer existed. That surfaced as three
  //   "ReferenceError: window is not defined" unhandled errors, which vitest
  //   reports as `Errors 3` and exits non-zero on even with every test
  //   passing — intermittently red-flagging unrelated PRs (#492 most recently).
  // - Dialog and ToastProvider both portal into document.body, and cleanup()
  //   alone leaves those portal siblings behind (same pattern as
  //   DocumentUploadModal.test.tsx) — hence the body sweep afterwards.
  cleanup();
  cleanupBody();
  vi.clearAllMocks();
});

function cleanupBody() {
  document.body.innerHTML = "";
}

describe("FlashcardImportModal shared deck across tabs (#183)", () => {
  it("keeps a deck built on another tab when switching back to Paste", () => {
    renderModal();

    // Build the deck off-Paste.
    fireEvent.click(tabButton("URL"));
    fireEvent.click(screen.getByRole("button", { name: "Inject mock deck" }));
    expect(importButton(2)).toBeInTheDocument();
    expect(screen.getByText(/2 valid/)).toBeInTheDocument();

    // Re-enter the Paste tab: its remount must NOT wipe the shared deck.
    fireEvent.click(tabButton("Paste"));
    expect(importButton(2)).toBeInTheDocument();
    expect(screen.getByText(/2 valid/)).toBeInTheDocument();
  });

  it("still clears the deck when the user deletes all Paste text", () => {
    renderModal();

    // Default tab is Paste; type two rows (tab-separated, newline rows).
    fireEvent.change(pasteTextarea(), {
      target: { value: "alpha\tbeta\ngamma\tdelta" },
    });
    expect(importButton(2)).toBeInTheDocument();

    // Deleting everything is an intentional clear — the deck must empty.
    fireEvent.change(pasteTextarea(), { target: { value: "" } });
    expect(importButton(0)).toBeInTheDocument();
  });

  it("re-parses on typing after switching back to Paste, replacing the deck", () => {
    renderModal();

    fireEvent.click(tabButton("URL"));
    fireEvent.click(screen.getByRole("button", { name: "Inject mock deck" }));
    expect(importButton(2)).toBeInTheDocument();

    // Back on Paste, typing must still drive the shared deck as before.
    fireEvent.click(tabButton("Paste"));
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta" } });
    expect(importButton(1)).toBeInTheDocument();
    expect(screen.getByText(/1 valid/)).toBeInTheDocument();
  });
});

describe("FlashcardImportModal request scope (#769)", () => {
  it("a request from a tab you left doesn't overwrite the deck", () => {
    renderModal();

    fireEvent.click(tabButton("URL"));
    fireEvent.click(screen.getByRole("button", { name: "Start slow fetch" }));
    fireEvent.click(tabButton("Paste"));
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta" } });
    expect(importButton(1)).toBeInTheDocument();

    act(() => { slow.deliver?.(URL_CARDS); });
    expect(importButton(1)).toBeInTheDocument();
  });

  it("leaving and re-entering the tab doesn't revive the old request", () => {
    renderModal();

    fireEvent.click(tabButton("URL"));
    fireEvent.click(screen.getByRole("button", { name: "Start slow fetch" }));
    fireEvent.click(tabButton("Paste"));
    fireEvent.click(tabButton("URL"));

    act(() => { slow.deliver?.(URL_CARDS); });
    expect(importButton(0)).toBeInTheDocument();
  });

  it("a request from before close + reopen doesn't land in the new session", () => {
    const { rerender } = renderModal();

    fireEvent.click(tabButton("URL"));
    fireEvent.click(screen.getByRole("button", { name: "Start slow fetch" }));
    rerender(modal(false));
    rerender(modal(true));

    act(() => { slow.deliver?.(URL_CARDS); });
    expect(importButton(0)).toBeInTheDocument();
  });

  it("the deck still lands when the request finishes on its own tab", () => {
    renderModal();

    fireEvent.click(tabButton("URL"));
    fireEvent.click(screen.getByRole("button", { name: "Start slow fetch" }));
    act(() => { slow.deliver?.(URL_CARDS); });
    expect(importButton(2)).toBeInTheDocument();
  });

  it("a parent re-render with a new courses array doesn't wipe the deck mid-edit", () => {
    const { rerender } = renderModal();

    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta\ngamma\tdelta" } });
    expect(importButton(2)).toBeInTheDocument();

    rerender(modal(true, [{ ...COURSE }]));
    expect(importButton(2)).toBeInTheDocument();
  });

  it("reopening still resets the deck", () => {
    const { rerender } = renderModal();

    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta" } });
    expect(importButton(1)).toBeInTheDocument();
    rerender(modal(false));
    rerender(modal(true));
    expect(importButton(0)).toBeInTheDocument();
  });
});
