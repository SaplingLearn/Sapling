// @vitest-environment jsdom
/**
 * Z08: the learning loop's transcript repeats class material verbatim — the
 * check pose (an item drafted from classmates' uploads), an H2 hint (a
 * classmate's passage), an H4 sibling, an H6 or template reference — in the
 * tutor's voice, with no model between the upload and the page. `markdown=
 * "inert"` draws those rows as text: a link shows where it points and is never
 * followed, nothing is fetched or embedded, no directive runs and no diagram
 * is drawn. Math and code still render. Every other host keeps the default.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

// The real renderer (ChatPanel loads it lazily through next/dynamic).
vi.mock("next/dynamic", async () => {
  const { MarkdownChat } = await import("./MarkdownChat");
  return { default: () => MarkdownChat };
});

import { ChatPanel, type ChatMsg } from "./ChatPanel";

afterEach(cleanup);

const CLASS_MATERIAL = [
  "Lab 4 is submitted through the course portal at https://lab4-portal.example/login before Friday.",
  "[Open the lab handout](https://evil.example/handout) and email help@evil.example.",
  "![the lab diagram](https://evil.example/pixel.png)",
  "::geogebra{id=abc123}",
  "```mermaid\nflowchart LR\n  A --> B\n```",
  "The rate is $\\frac{1}{2}$ per step, and `x = 1` in code.",
].join("\n\n");

const ROWS: ChatMsg[] = [{ id: "h2", role: "assistant", content: CLASS_MATERIAL }];

describe("ChatPanel markdown=inert (the learning loop's transcript)", () => {
  it("shows class material's links with where they point, and follows, fetches and embeds nothing", () => {
    render(<ChatPanel messages={ROWS} onSend={() => {}} turnStyle="page" markdown="inert" />);
    const log = screen.getByTestId("tutor-messages");
    expect(log.querySelector("a")).toBeNull();
    expect(log.querySelector("img")).toBeNull();
    expect(log.querySelector("iframe")).toBeNull();
    const text = log.textContent ?? "";
    expect(text).toContain("https://lab4-portal.example/login"); // a bare URL stays readable text
    expect(text).toContain("Open the lab handout (evil.example)"); // a link names its destination
    expect(text).toContain("[image: the lab diagram]");
    expect(text).toContain("::geogebra{id=abc123}"); // a directive is text, never a frame
    expect(text).toContain("flowchart LR"); // a diagram fence is shown as the code it is
    expect(log.querySelector(".katex")).not.toBeNull(); // math still renders
    expect(log.querySelector("code")).not.toBeNull();
  });

  it("a link whose words name one site shows the host it really points at", () => {
    const disguised: ChatMsg[] = [
      { id: "h4", role: "assistant", content: "Submit at [https://bu.edu/portal](https://evil.example/collect)." },
    ];
    render(<ChatPanel messages={disguised} onSend={() => {}} markdown="inert" />);
    const log = screen.getByTestId("tutor-messages");
    expect(log.querySelector("a")).toBeNull();
    expect(log.textContent).toContain("https://bu.edu/portal (evil.example)");
  });

  it("the streaming turn is drawn the same way", () => {
    render(<ChatPanel messages={[]} onSend={() => {}} streamingText={CLASS_MATERIAL} markdown="inert" />);
    const log = screen.getByTestId("tutor-messages");
    expect(log.querySelector("a")).toBeNull();
    expect(log.querySelector("iframe")).toBeNull();
  });

  it("every other host keeps the default renderer: live links and embeds as before", () => {
    render(<ChatPanel messages={ROWS} onSend={() => {}} />);
    const log = screen.getByTestId("tutor-messages");
    expect(log.querySelector('a[href="https://evil.example/handout"]')).not.toBeNull();
    expect(log.querySelector('a[href="https://lab4-portal.example/login"]')).not.toBeNull();
    expect(log.querySelector("iframe.sap-geogebra, iframe")).not.toBeNull();
  });
});
