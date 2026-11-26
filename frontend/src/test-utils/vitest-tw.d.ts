// The toHaveTwStyle matcher registered in vitest.setup.ts.
import "vitest";

declare module "vitest" {
  interface Assertion<T> {
    /** Like toHaveStyle, but also passes when the declaration is the
     *  Tailwind class the inline-style codemod makes of it. */
    toHaveTwStyle(expected: Record<string, string | number>): T;
  }
}
