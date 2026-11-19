// @vitest-environment jsdom
/**
 * Tutor V2 (wireframe T6, PR #866 U7a): "Tutor messages sit on the page (no
 * bubble, like Claude); your messages are bubbles on the right." ChatPanel's
 * `turnStyle="page"` draws a tutor turn under the tutor's mark with no bubble,
 * keeps the key-idea block and a readable measure, and leaves the student's
 * own bubble as it was. The default (`bubble`) is unchanged for its other
 * hosts (the quiz's Ask panel, the legacy Learn screen).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

vi.mock("next/dynamic", () => ({
  default: () => ({ children }: { children: string }) => <div data-testid="md">{children}</div>,
}));

import { ChatPanel, PageTurn, type ChatMsg } from "./ChatPanel";
import styles from "./ChatPanel.module.css";

afterEach(cleanup);

const MESSAGES: ChatMsg[] = [
  { id: "t1", role: "assistant", content: "Key idea: Every recursive call needs a base case.\n\nWhat happens without one?" },
  { id: "u1", role: "user", content: "It never stops?" },
];

/** The element that would paint a bubble: a background or a border of its own. */
function hasBubble(el: HTMLElement): boolean {
  for (let node: HTMLElement | null = el; node && node.dataset.testid !== "tutor-messages"; node = node.parentElement) {
    const { background, border } = node.style;
    if ((background && background !== "transparent") || (border && border !== "none")) return true;
  }
  return false;
}

describe("ChatPanel turnStyle=page", () => {
  it("draws the tutor's turn on the page under its mark, with the key-idea block", () => {
    render(<ChatPanel messages={MESSAGES} onSend={() => {}} turnStyle="page" />);
    const turns = screen.getAllByTestId("tutor-turn");
    expect(turns).toHaveLength(1);
    const turn = turns[0];
    // the tutor's mark: its avatar and name, read as "Tutor:"
    expect(turn.querySelector(`.${styles.turnMark}`)?.textContent).toBe("Tutor:");
    // no bubble anywhere between the text and the log
    const text = turn.querySelector<HTMLElement>(`.${styles.turnText}`)!;
    expect(hasBubble(text)).toBe(false);
    // a readable measure (the module's 72ch), not the column's whole width
    expect(text.className).toContain(styles.turnText);
    // the key idea keeps its labelled block
    expect(within(turn).getByTestId("tutor-key-idea").textContent).toBe("Key idea: Every recursive call needs a base case.");
    expect(turn.textContent).toContain("What happens without one?");
  });

  it("keeps the student's message a bubble on the right", () => {
    render(<ChatPanel messages={MESSAGES} onSend={() => {}} turnStyle="page" />);
    const mine = screen.getByText("It never stops?");
    const row = mine.parentElement!.parentElement!;
    expect(row.style.alignSelf).toBe("flex-end");
    expect(mine.parentElement!.style.background).toBe("var(--accent)");
  });

  it("draws a streaming reply on the page too", () => {
    render(<ChatPanel messages={[]} onSend={() => {}} turnStyle="page" streamingText="" streamingStatus="Checking your progress…" />);
    const turn = screen.getByTestId("tutor-turn");
    expect(turn.textContent).toContain("Checking your progress…");
    expect(hasBubble(turn.querySelector<HTMLElement>(`.${styles.turnText}`)!)).toBe(false);
  });

  it("keeps a turn that is shown elsewhere in the log but unpainted", () => {
    render(<ChatPanel messages={[{ ...MESSAGES[0], visuallyHidden: true }]} onSend={() => {}} turnStyle="page" />);
    const turn = screen.getByTestId("tutor-turn");
    expect(turn.dataset.visuallyHidden).toBe("true");
    expect(turn.style.position).toBe("absolute");
  });

  it("leaves the default bubble as it was", () => {
    render(<ChatPanel messages={MESSAGES} onSend={() => {}} />);
    expect(screen.queryByTestId("tutor-turn")).toBeNull();
    const block = screen.getByTestId("tutor-key-idea");
    expect(hasBubble(block)).toBe(true);
  });
});

describe("PageTurn", () => {
  it("keeps a plain turn's own line breaks", () => {
    render(<PageTurn plain testId="greeting">{"Welcome.\n\nA quick check-in first."}</PageTurn>);
    const body = screen.getByTestId("greeting");
    expect(body.className).toContain(styles.turnPlain);
    expect(body.textContent).toBe("Welcome.\n\nA quick check-in first.");
  });
});
