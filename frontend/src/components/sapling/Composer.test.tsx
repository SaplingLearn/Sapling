// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SaplingComposer, isSendKey, type SaplingComposerProps } from "./Composer";

afterEach(cleanup);

function Harness(props: Partial<SaplingComposerProps> & { initial?: string }) {
  const [value, setValue] = React.useState(props.initial ?? "");
  return <SaplingComposer value={value} onChange={setValue} onSend={props.onSend ?? (() => {})} {...props} />;
}

describe("isSendKey", () => {
  const ev = (key: string, extra: Record<string, unknown> = {}) =>
    ({ key, shiftKey: false, nativeEvent: { isComposing: false, keyCode: 13 }, ...extra }) as never;

  it("sends on Enter only", () => {
    expect(isSendKey(ev("Enter"))).toBe(true);
    expect(isSendKey(ev("a"))).toBe(false);
    expect(isSendKey(ev("Enter", { shiftKey: true }))).toBe(false);
  });

  it("never sends during IME composition", () => {
    expect(isSendKey(ev("Enter", { nativeEvent: { isComposing: true } }))).toBe(false);
    expect(isSendKey(ev("Enter", { nativeEvent: { isComposing: false, keyCode: 229 } }))).toBe(false);
  });
});

describe("SaplingComposer", () => {
  it("has a labelled field and sends trimmed text on Enter without clearing the draft", () => {
    const onSend = vi.fn();
    render(<Harness initial="  Why is the base case needed?  " onSend={onSend} />);
    const field = screen.getByRole("textbox", { name: "Message Clov" });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("Why is the base case needed?");
    expect((field as HTMLTextAreaElement).value).toBe("  Why is the base case needed?  ");
  });

  it("does not send on Shift+Enter, while composing, or when empty", () => {
    const onSend = vi.fn();
    const { unmount } = render(<Harness initial="draft" onSend={onSend} />);
    const field = screen.getByRole("textbox");
    fireEvent.keyDown(field, { key: "Enter", shiftKey: true });
    fireEvent.keyDown(field, { key: "Enter", isComposing: true });
    expect(onSend).not.toHaveBeenCalled();
    unmount();
    render(<Harness initial="   " onSend={onSend} />);
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("swaps Send for Stop while a reply streams, and blocks a conflicting send", () => {
    const onSend = vi.fn();
    const onStop = vi.fn();
    render(<Harness initial="next" state="streaming" onSend={onSend} onStop={onStop} />);
    expect(screen.getByRole("status")).toHaveTextContent("Clov is responding…");
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("explains why a turn is unavailable instead of silently ignoring it", () => {
    const onSend = vi.fn();
    render(<Harness initial="hi" canSend={false} disabledReason="Chat is paused until tomorrow." onSend={onSend} />);
    const field = screen.getByRole("textbox");
    expect(field).toHaveAccessibleDescription(expect.stringContaining("Chat is paused until tomorrow."));
    fireEvent.keyDown(field, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
  });
});
