// @vitest-environment jsdom
/**
 * The review's session view: the per-card strip and running tally follow the
 * ratings, the end of the deck is a summary with a second pass through what
 * was missed, and a deleted card stops counting.
 *
 * The #769 races (one rating per card, a failed rating does not advance) are
 * pinned through the page in screens/Flashcards.races.test.tsx.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, act, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/lib/api", () => ({
  rateFlashcard: vi.fn(),
  deleteFlashcard: vi.fn(),
}));

import { rateFlashcard, deleteFlashcard } from "@/lib/api";
import { ToastProvider } from "../../ToastProvider";
import type { Card } from "../home/flashcardsModel";
import { Review } from "./Review";

const mockedRate = vi.mocked(rateFlashcard);
const mockedDelete = vi.mocked(deleteFlashcard);

const card = (id: string, topic = "Recursion"): Card => ({ id, topic, front: `Q-${id}`, back: `A-${id}`, course_id: "c1" });
const DECK = [card("a"), card("b"), card("c", "Sorting")];

const onAllSets = vi.fn();

/** The page's part: it owns the deck, and drops a deleted card from it. */
function Harness({ deck: initial, fromHome = true }: { deck: Card[]; fromHome?: boolean }) {
  const [deck, setDeck] = React.useState(initial);
  return (
    <ToastProvider>
      <Review
        deck={deck}
        accent="#4f86e0"
        fromHome={fromHome}
        onRated={() => {}}
        onDeleted={id => setDeck(d => d.filter(c => c.id !== id))}
        onAllSets={onAllSets}
      />
    </ToastProvider>
  );
}

const flip = () => fireEvent.keyDown(window, { code: "Space", key: " " });
const press = (key: string) => fireEvent.keyDown(window, { key, code: `Digit${key}` });
const flipCard = async () => {
  act(() => { flip(); });
  await waitFor(() => expect(screen.getByTitle(/\(press 3\)/)).toBeEnabled());
};
/** Flip the card that is up and rate it: 1 forgot, 2 hard, 3 easy. */
const rate = async (key: "1" | "2" | "3") => {
  await flipCard();
  await act(async () => { press(key); });
};

const strip = () => screen.getAllByTestId("flashcards-segment").map(s => `${s.getAttribute("data-rated")}${s.getAttribute("data-current") === "true" ? "*" : ""}`);
const counts = () => ["easy", "hard", "forgot"].map(kind => Number(screen.getByTestId(`flashcards-tally-${kind}`).textContent?.match(/\d+/)?.[0]));

beforeEach(() => {
  vi.resetAllMocks();
  mockedRate.mockResolvedValue({ ok: true });
  mockedDelete.mockResolvedValue({ ok: true });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Review: progress", () => {
  it("has one segment per card; each takes its rating, and the current one is marked", async () => {
    render(<Harness deck={DECK} />);
    expect(screen.getByText("Card 1 of 3")).toBeTruthy();
    expect(strip()).toEqual(["unseen*", "unseen", "unseen"]);

    await rate("3");
    await screen.findByText("Card 2 of 3");
    expect(strip()).toEqual(["easy", "unseen*", "unseen"]);

    await rate("1");
    await screen.findByText("Card 3 of 3");
    expect(strip()).toEqual(["easy", "forgot", "unseen*"]);
    expect(screen.getByRole("progressbar", { name: "Cards reviewed" }).getAttribute("aria-valuenow")).toBe("3");
  });

  it("keeps a running tally of easy, hard and forgot beside the card count", async () => {
    render(<Harness deck={DECK} />);
    expect(counts()).toEqual([0, 0, 0]);

    await rate("2");
    await screen.findByText("Card 2 of 3");
    expect(counts()).toEqual([0, 1, 0]);
    await rate("3");
    await screen.findByText("Card 3 of 3");
    expect(counts()).toEqual([1, 1, 0]);
    expect(screen.getByRole("group", { name: "This session: 1 easy, 1 hard, 0 forgot" })).toBeTruthy();
  });

  it("a rating that fails to save colours nothing and counts nothing", async () => {
    mockedRate.mockRejectedValueOnce(new Error("boom"));
    render(<Harness deck={DECK} />);
    await rate("3");

    expect(await screen.findByText(/Couldn't save that rating/)).toBeTruthy();
    expect(strip()).toEqual(["unseen*", "unseen", "unseen"]);
    expect(counts()).toEqual([0, 0, 0]);
  });

  it("a deck past 40 cards shows one continuous bar instead", () => {
    render(<Harness deck={Array.from({ length: 41 }, (_, i) => card(`k${i}`))} />);
    expect(screen.getByText("Card 1 of 41")).toBeTruthy();
    expect(screen.queryAllByTestId("flashcards-segment")).toHaveLength(0);
    expect(screen.getByTestId("flashcards-progress-bar")).toBeTruthy();
  });
});

describe("Review: the card and the ratings", () => {
  it("names the card's concept on the question side and flips to the answer", async () => {
    render(<Harness deck={DECK} />);
    expect(screen.getByTestId("flashcards-topic").textContent).toBe("Recursion");
    // The sides are not labelled: the flip itself says which one is showing.
    expect(screen.queryByText("Question")).toBeNull();
    expect(screen.queryByText("Answer")).toBeNull();
    const inner = screen.getByTestId("flashcards-card");
    expect(inner.getAttribute("data-flipped")).toBe("false");

    await flipCard();
    expect(inner.getAttribute("data-flipped")).toBe("true");
    // Clicking the card flips it back.
    await userEvent.click(inner);
    expect(inner.getAttribute("data-flipped")).toBe("false");
  });

  it("the three rating buttons keep their names, key hints and disabled-until-flipped state", async () => {
    render(<Harness deck={DECK} />);
    const buttons = ["forgot (press 1)", "hard (press 2)", "easy (press 3)"].map(title => screen.getByTitle(title));
    expect(buttons.map(b => b.getAttribute("data-kind"))).toEqual(["forgot", "hard", "easy"]);
    expect(buttons.map(b => within(b).getByText(/^[123]$/).textContent)).toEqual(["1", "2", "3"]);
    for (const b of buttons) expect(b).toBeDisabled();

    await flipCard();
    for (const b of buttons) expect(b).toBeEnabled();
    await userEvent.click(buttons[1]);
    expect(mockedRate).toHaveBeenCalledWith("u1", "a", 2);
    expect(await screen.findByText("Card 2 of 3")).toBeTruthy();
  });

  it("the rating keys do nothing before the flip", async () => {
    render(<Harness deck={DECK} />);
    act(() => { press("3"); });
    expect(mockedRate).not.toHaveBeenCalled();
    expect(screen.getByText("Card 1 of 3")).toBeTruthy();
  });
});

describe("Review: deck complete", () => {
  const finish = async (keys: ("1" | "2" | "3")[]) => {
    for (const [i, key] of keys.entries()) {
      await rate(key);
      if (i < keys.length - 1) await screen.findByText(`Card ${i + 2} of ${keys.length}`);
    }
    return screen.findByTestId("flashcards-summary");
  };

  it("shows how the session went: a stacked bar and the three counts", async () => {
    render(<Harness deck={DECK} />);
    const summary = within(await finish(["3", "2", "1"]));

    expect(summary.getByText("Deck complete")).toBeTruthy();
    expect(counts()).toEqual([1, 1, 1]);
    expect(summary.getByRole("img", { name: "This session: 1 easy, 1 hard, 1 forgot" })).toBeTruthy();
    expect(["easy", "hard", "forgot"].map(kind => summary.getByTestId(`flashcards-stack-${kind}`).style.flexGrow)).toEqual(["1", "1", "1"]);
    expect(screen.queryByText(/Card \d of/)).toBeNull();
  });

  it("the stacked bar has no part for a rating nobody gave", async () => {
    render(<Harness deck={DECK} />);
    const summary = within(await finish(["3", "3", "1"]));
    expect(summary.getByTestId("flashcards-stack-easy").style.flexGrow).toBe("2");
    expect(summary.queryByTestId("flashcards-stack-hard")).toBeNull();
  });

  it("Review the N you missed restarts with only the cards rated hard or forgot", async () => {
    render(<Harness deck={DECK} />);
    await finish(["3", "2", "1"]);

    await userEvent.click(screen.getByRole("button", { name: "Review the 2 you missed" }));

    // Cards b and c, in deck order, with a clean slate.
    expect(await screen.findByText("Card 1 of 2")).toBeTruthy();
    expect(strip()).toEqual(["unseen*", "unseen"]);
    expect(counts()).toEqual([0, 0, 0]);
    await rate("3");
    expect(mockedRate).toHaveBeenLastCalledWith("u1", "b", 3);
    await screen.findByText("Card 2 of 2");
    expect(screen.getByTestId("flashcards-topic").textContent).toBe("Sorting");
    await rate("3");
    expect(mockedRate).toHaveBeenLastCalledWith("u1", "c", 3);

    // That round's result, with nothing missed in it; again is the whole deck.
    await screen.findByTestId("flashcards-summary");
    expect(counts()).toEqual([2, 0, 0]);
    expect(screen.queryByRole("button", { name: /you missed/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(await screen.findByText("Card 1 of 3")).toBeTruthy();
    expect(strip()).toEqual(["unseen*", "unseen", "unseen"]);
  });

  it("offers nothing to re-review when every card was easy", async () => {
    render(<Harness deck={DECK} />);
    await finish(["3", "3", "3"]);
    expect(screen.queryByRole("button", { name: /you missed/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Review again" })).toBeTruthy();
  });

  it("offers the way back to all sets only when the review was started from the home", async () => {
    render(<Harness deck={DECK.slice(0, 1)} />);
    await finish(["3"]);
    await userEvent.click(screen.getByRole("button", { name: "All sets" }));
    expect(onAllSets).toHaveBeenCalledTimes(1);

    cleanup();
    render(<Harness deck={DECK.slice(0, 1)} fromHome={false} />);
    await finish(["3"]);
    expect(screen.queryByRole("button", { name: "All sets" })).toBeNull();
  });
});

describe("Review: deleting a card", () => {
  it("a deleted card leaves the strip and the tally; what else was rated stays", async () => {
    render(<Harness deck={DECK} />);
    await rate("3");
    await screen.findByText("Card 2 of 3");
    await rate("1");
    await screen.findByText("Card 3 of 3");
    expect(counts()).toEqual([1, 0, 1]);

    // Deleting restarts the deck at its first card (a, rated easy).
    await userEvent.click(screen.getByRole("button", { name: /delete card/i }));
    expect(await screen.findByText("Card 1 of 2")).toBeTruthy();
    expect(mockedDelete).toHaveBeenCalledWith("u1", "c");
    expect(strip()).toEqual(["easy*", "forgot"]);
    expect(counts()).toEqual([1, 0, 1]);

    // Deleting a rated card takes its rating out of the tally.
    await userEvent.click(screen.getByRole("button", { name: /delete card/i }));
    expect(await screen.findByText("Card 1 of 1")).toBeTruthy();
    expect(mockedDelete).toHaveBeenLastCalledWith("u1", "a");
    expect(strip()).toEqual(["forgot*"]);
    expect(counts()).toEqual([0, 0, 1]);
  });

  it("Delete pressed twice while it saves deletes the card once, and reports no failure", async () => {
    let done!: (r: { ok: boolean }) => void;
    mockedDelete.mockReturnValueOnce(new Promise(resolve => { done = resolve; }));
    // What the server says to a second delete of the same card.
    mockedDelete.mockRejectedValue(Object.assign(new Error('{"detail":"Flashcard not found"}'), { status: 404 }));
    render(<Harness deck={DECK} />);
    const del = screen.getByRole("button", { name: /delete card/i });

    fireEvent.click(del);
    fireEvent.click(del);
    await act(async () => { done({ ok: true }); });

    expect(await screen.findByText("Card 1 of 2")).toBeTruthy();
    expect(mockedDelete).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Couldn't delete that card|couldn't find that/i)).toBeNull();
  });

  it("a card is not deleted while its rating is still saving", async () => {
    let saved!: (r: { ok: boolean }) => void;
    mockedRate.mockReturnValueOnce(new Promise(resolve => { saved = resolve; }));
    render(<Harness deck={DECK} />);
    await flipCard();
    act(() => { press("3"); });

    fireEvent.click(screen.getByRole("button", { name: /delete card/i }));
    expect(mockedDelete).not.toHaveBeenCalled();

    // The rating lands on the card it was given to, and moves on from it.
    await act(async () => { saved({ ok: true }); });
    expect(await screen.findByText("Card 2 of 3")).toBeTruthy();
    expect(counts()).toEqual([1, 0, 0]);
  });

  it("deleting the last card says the deck is empty and offers the way back", async () => {
    render(<Harness deck={DECK.slice(0, 1)} />);
    await userEvent.click(screen.getByRole("button", { name: /delete card/i }));
    expect(await screen.findByText("No cards left here")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Back to all sets" }));
    expect(onAllSets).toHaveBeenCalled();
  });

  it("the arrow keys move back and forth without rating, and the hint says so", async () => {
    render(<Harness deck={[card("a"), card("b"), card("c")]} />);
    const arrow = (key: "ArrowLeft" | "ArrowRight") => act(() => { fireEvent.keyDown(window, { key, code: key }); });
    await screen.findByText("Card 1 of 3");
    expect(screen.getByText(/← → to go back and forth/)).toBeTruthy();

    // Left at the first card does nothing (no wrap).
    arrow("ArrowLeft");
    expect(screen.getByText("Card 1 of 3")).toBeTruthy();

    arrow("ArrowRight");
    expect(screen.getByText("Card 2 of 3")).toBeTruthy();
    arrow("ArrowRight");
    expect(screen.getByText("Card 3 of 3")).toBeTruthy();
    // Right at the last card does not finish the deck.
    arrow("ArrowRight");
    expect(screen.getByText("Card 3 of 3")).toBeTruthy();
    expect(screen.queryByText("Deck complete")).toBeNull();

    arrow("ArrowLeft");
    expect(screen.getByText("Card 2 of 3")).toBeTruthy();
    // Nothing was rated on the way: skipped cards stay unseen.
    expect(mockedRate).not.toHaveBeenCalled();
    expect(strip()).toEqual(["unseen", "unseen*", "unseen"]);
  });

  it("moving off a flipped card shows the next one question side up", async () => {
    render(<Harness deck={[card("a"), card("b")]} />);
    await flipCard();
    expect(screen.getByTestId("flashcards-card").getAttribute("data-flipped")).toBe("true");
    act(() => { fireEvent.keyDown(window, { key: "ArrowRight", code: "ArrowRight" }); });
    expect(screen.getByText("Card 2 of 2")).toBeTruthy();
    expect(screen.getByTestId("flashcards-card").getAttribute("data-flipped")).toBe("false");
  });

  it("the up and down arrows flip the card, either way", () => {
    render(<Harness deck={[card("a"), card("b")]} />);
    const inner = screen.getByTestId("flashcards-card");
    const press = (key: "ArrowUp" | "ArrowDown") => act(() => { fireEvent.keyDown(window, { key, code: key }); });
    press("ArrowDown");
    expect(inner.getAttribute("data-flipped")).toBe("true");
    press("ArrowUp");
    expect(inner.getAttribute("data-flipped")).toBe("false");
    press("ArrowUp");
    expect(inner.getAttribute("data-flipped")).toBe("true");
    // Still on the first card: flipping never moves through the deck.
    expect(screen.getByText("Card 1 of 2")).toBeTruthy();
    expect(screen.getByText(/Space or ↑ ↓ to flip/)).toBeTruthy();
  });

  it("a card you go back to can be rated again, and the tally follows the new rating", async () => {
    render(<Harness deck={[card("a"), card("b")]} />);
    await rate("1");
    expect(counts()).toEqual([0, 0, 1]);
    act(() => { fireEvent.keyDown(window, { key: "ArrowLeft", code: "ArrowLeft" }); });
    expect(screen.getByText("Card 1 of 2")).toBeTruthy();
    await rate("3");
    expect(counts()).toEqual([1, 0, 0]);
    expect(mockedRate).toHaveBeenCalledTimes(2);
  });
});
