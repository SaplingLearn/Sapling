// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { AnimatedNumber } from "./AnimatedNumber";

// vitest.setup.ts stubs matchMedia to prefers-reduced-motion: reduce, so the
// tween is skipped and every value lands at once.
afterEach(cleanup);

describe("AnimatedNumber", () => {
  it("paints the real value first and jumps to a new one under reduced motion", () => {
    const fmt = (v: number) => `$${v.toFixed(2)}`;
    const { rerender } = render(<AnimatedNumber value={1.5} format={fmt} data-testid="n" />);
    expect(screen.getByTestId("n")).toHaveTextContent("$1.50");
    rerender(<AnimatedNumber value={42} format={fmt} data-testid="n" />);
    expect(screen.getByTestId("n")).toHaveTextContent("$42.00");
  });

  it("formats with a rounded locale string by default", () => {
    render(<AnimatedNumber value={12345.6} data-testid="n" />);
    expect(screen.getByTestId("n")).toHaveTextContent((12346).toLocaleString());
  });
});
