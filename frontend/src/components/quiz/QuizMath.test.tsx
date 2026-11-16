// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QuizMath } from "./QuizMath";

describe("QuizMath", () => {
  it("renders inline and display equations alongside plain text", () => {
    const { container } = render(
      <QuizMath text={String.raw`Solve \(x^2 = 4\). Then evaluate \[\frac{1}{2}\].`} />,
    );
    expect(screen.getByText(/Solve/)).toBeInTheDocument();
    expect(container.querySelectorAll("math")).toHaveLength(2);
    expect(container.querySelector(".quiz-math-display math")?.getAttribute("display")).toBe("block");
  });

  it("leaves prices and invalid expressions readable", () => {
    const text = String.raw`The price rose from $5 to $8. \(\invalidcommand\)`;
    render(<QuizMath text={text} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });
});
