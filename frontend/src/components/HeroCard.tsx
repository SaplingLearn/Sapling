"use client";

import React from "react";

/**
 * The warm hero surface shared by the sign-in and beta modals (#288).
 *
 * Thin on purpose: it owns the two classes and nothing else, so callers keep
 * their own layout, sizing and dialog semantics in `style`/props. The visual
 * itself lives in `.card--hero` (globals.css), backed by the
 * `--surface-hero` / `--surface-hero-shadow` tokens.
 *
 * Before this existed, the gradient was pasted at five sites and had drifted
 * at four of them — three shadow alphas, two radii, one missing inset. The
 * point of the component is that there is now one place for it to drift.
 *
 * The shadow's base colour is the one value that had NOT drifted (every site
 * used slate `rgba(15,23,42)`); adopting the token deliberately re-tints it
 * to the warm `--sap-900` the app's other shadows use. See globals.css.
 *
 * For a panel nested INSIDE a hero card, use the `.hero-surface` class
 * directly: it applies the gradient without restating the parent's border,
 * radius or shadow.
 */
export type HeroCardProps = React.ComponentPropsWithoutRef<"div">;

export const HeroCard = React.forwardRef<HTMLDivElement, HeroCardProps>(
  function HeroCard({ className, children, ...rest }, ref) {
    return (
      <div
        ref={ref}
        className={["card", "card--hero", className].filter(Boolean).join(" ")}
        {...rest}
      >
        {children}
      </div>
    );
  },
);

export default HeroCard;
