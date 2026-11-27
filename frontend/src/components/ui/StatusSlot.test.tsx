// @vitest-environment jsdom
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StatusSlot, type StatusNotice } from "./StatusSlot";

afterEach(cleanup);

const notice = (key: string, on: boolean): StatusNotice => ({ key, on, render: () => <p>{key} notice</p> });

describe("StatusSlot", () => {
  it("shows only the first notice that is on", () => {
    render(<StatusSlot testId="slot" notices={[notice("paused", false), notice("offer", true), notice("materials", true)]} />);
    const slot = screen.getByTestId("slot");
    expect(slot.textContent).toBe("offer notice");
    expect(slot.getAttribute("data-notice")).toBe("offer");
    expect(slot.getAttribute("data-has-notices")).toBe("true");
  });

  it("the next notice takes the slot when the first clears", () => {
    const { rerender } = render(<StatusSlot testId="slot" notices={[notice("paused", true), notice("materials", true)]} />);
    expect(screen.getByTestId("slot").getAttribute("data-notice")).toBe("paused");
    rerender(<StatusSlot testId="slot" notices={[notice("paused", false), notice("materials", true)]} />);
    expect(screen.getByTestId("slot").getAttribute("data-notice")).toBe("materials");
  });

  it("stays in the DOM as a polite live region with nothing to show", () => {
    render(<StatusSlot testId="slot" notices={[notice("paused", false)]} />);
    const slot = screen.getByTestId("slot");
    expect(slot.getAttribute("aria-live")).toBe("polite");
    expect(slot.getAttribute("data-has-notices")).toBe("false");
    expect(slot.textContent).toBe("");
  });
});
