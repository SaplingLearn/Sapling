// @vitest-environment jsdom
/**
 * Flashcard generators answered by the crisis screen
 * (docs/safety/crisis-support.md): describing a set, generating from pasted
 * text and making cloze cards each show the card as a dialog and do none of
 * their own work — no cards reach the deck, nothing is sorted, no error toast.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import crisisFixture from "@/test-utils/crisisSupport.json";

const { toast } = vi.hoisted(() => ({
  toast: { success: vi.fn(), error: vi.fn(), warn: vi.fn() },
}));

vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("../ToastProvider", () => ({ useToast: () => toast }));
vi.mock("../Icon", () => ({ Icon: () => null }));
vi.mock("@/lib/api", () => ({ importGenerate: vi.fn(), importCloze: vi.fn() }));
vi.mock("@/lib/flashcardSetsApi", () => ({ SUGGEST_MIN: 3, SUGGEST_MAX: 300, suggestFlashcardSet: vi.fn() }));

import { importCloze, importGenerate } from "@/lib/api";
import { suggestFlashcardSet } from "@/lib/flashcardSetsApi";
import { AiTab } from "./tabs/AiTab";
import { PasteTab } from "./tabs/PasteTab";
import { Hero } from "./home/Hero";

const CRISIS = { reply: "the card as text", crisis_support: crisisFixture };

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

async function expectCardDialog() {
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent(crisisFixture.title);
  expect(toast.error).not.toHaveBeenCalled();
  expect(toast.success).not.toHaveBeenCalled();
  fireEvent.click(screen.getByTestId("crisis-support-dismiss"));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
}

describe("flashcards — crisis support", () => {
  it("Generate from pasted text shows the card and adds no cards", async () => {
    vi.mocked(importGenerate).mockResolvedValueOnce({ cards: [], ...CRISIS } as never);
    const onCards = vi.fn();
    render(<AiTab documents={[]} onCards={onCards} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "i want to kill myself" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate cards" }));
    await expectCardDialog();
    expect(onCards).not.toHaveBeenCalled();
  });

  it("Generate cloze cards shows the card and adds no cards", async () => {
    vi.mocked(importCloze).mockResolvedValueOnce({ cards: [], ...CRISIS } as never);
    const onCards = vi.fn();
    render(<PasteTab cards={[]} onCards={onCards} />);
    fireEvent.click(screen.getByRole("button", { name: "Cloze deletion (AI)" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "i want to kill myself" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate cloze cards" }));
    await expectCardDialog();
    expect(onCards).not.toHaveBeenCalled();
  });

  it("Describing a set shows the card and sorts nothing", async () => {
    vi.mocked(suggestFlashcardSet).mockResolvedValueOnce(
      { name: "", concepts: [], considered: 0, backend: "none", ...CRISIS } as never,
    );
    const onSorted = vi.fn();
    render(
      <Hero
        courseId="c1"
        columns={[]}
        canSort
        examples={[]}
        figures={{ cards: 0, concepts: 0, sets: 0 }}
        onSorted={onSorted}
      />,
    );
    fireEvent.change(screen.getByLabelText("Describe a set"), { target: { value: "i want to kill myself" } });
    fireEvent.click(screen.getByRole("button", { name: /Sort it/ }));
    await expectCardDialog();
    expect(onSorted).not.toHaveBeenCalled();
  });
});
