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
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
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

vi.mock("./tabs/UrlTab", async () => {
  const { createElement } = await import("react");
  return {
    UrlTab: ({ onCards }: { onCards: (next: typeof URL_CARDS) => void }) =>
      createElement(
        "button",
        { type: "button", onClick: () => onCards(URL_CARDS) },
        "Inject mock deck",
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

function renderModal() {
  return render(
    <ToastProvider>
      <FlashcardImportModal
        open
        onClose={() => {}}
        courses={[COURSE]}
        documents={[]}
        onImported={() => {}}
      />
    </ToastProvider>,
  );
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
