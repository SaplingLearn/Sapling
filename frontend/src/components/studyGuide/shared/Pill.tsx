import React from "react";

import s from "./pieces.module.css";

/** A short label in a pill: what a guide is for, its goal or its depth. */
export function Pill({ children }: { children: React.ReactNode }) {
  return <span className={s.pill}>{children}</span>;
}
