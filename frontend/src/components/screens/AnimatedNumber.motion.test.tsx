// @vitest-environment jsdom
// Its own file: framer-motion reads prefers-reduced-motion once per module
// instance, and the other file runs under vitest.setup.ts's reduce stub.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { AnimatedNumber } from "./AnimatedNumber";

afterEach(cleanup);

describe("AnimatedNumber with motion", () => {
  it("tweens from the old figure to the new one without flashing the new value first", async () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: false, media: query, onchange: null,
      addListener: () => {}, removeListener: () => {},
      addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
    })) as typeof window.matchMedia;
    try {
      const { rerender } = render(<AnimatedNumber value={0} data-testid="n" />);
      expect(screen.getByTestId("n")).toHaveTextContent("0");
      rerender(<AnimatedNumber value={1000} data-testid="n" />);
      expect(screen.getByTestId("n")).not.toHaveTextContent((1000).toLocaleString());
      await waitFor(() => expect(screen.getByTestId("n")).toHaveTextContent((1000).toLocaleString()));
    } finally {
      window.matchMedia = original;
    }
  });
});
