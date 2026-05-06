// Extends Vitest's `expect` with the @testing-library/jest-dom matchers
// (.toBeInTheDocument, .toHaveTextContent, .toHaveAttribute, etc.).
// Loaded only for tests that opt into a DOM via // @vitest-environment jsdom;
// the matchers themselves are no-ops when there's no document.
import "@testing-library/jest-dom/vitest";
