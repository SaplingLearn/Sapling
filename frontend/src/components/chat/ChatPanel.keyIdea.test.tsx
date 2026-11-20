// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next/dynamic", () => ({
  default: () => ({ children }: { children: string }) => <div data-testid="md">{children}</div>,
}));

import { ChatPanel, splitKeyIdea } from "./ChatPanel";

describe("splitKeyIdea", () => {
  it("lifts each 'Key idea:' paragraph out where it stands", () => {
    expect(splitKeyIdea("Key idea: Bits are places.\n\nTry 110.")).toEqual([
      { kind: "key", text: "Bits are places." },
      { kind: "text", text: "Try 110." },
    ]);
    expect(splitKeyIdea("The answer: 6.\n\nKey idea: Add the places.\n\nOne more?")).toEqual([
      { kind: "text", text: "The answer: 6." },
      { kind: "key", text: "Add the places." },
      { kind: "text", text: "One more?" },
    ]);
    expect(splitKeyIdea("No label here.")).toEqual([{ kind: "text", text: "No label here." }]);
    expect(splitKeyIdea("Key idea:   ")).toEqual([{ kind: "text", text: "Key idea:   " }]);
  });

  it("renders the key idea as the labelled block, still reading 'Key idea: …'", () => {
    render(
      <ChatPanel
        messages={[{ id: "a", role: "assistant", content: "Key idea: Bits are places.\n\nTry 110." }]}
        onSend={() => {}}
      />,
    );
    const block = screen.getByTestId("tutor-key-idea");
    expect(block.textContent).toBe("Key idea: Bits are places.");
    expect(screen.getByTestId("tutor-messages").textContent).toContain("Try 110.");
  });
});
