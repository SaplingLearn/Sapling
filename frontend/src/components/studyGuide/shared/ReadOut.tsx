import React from "react";

import s from "./pieces.module.css";

/** Words a screen reader reads out that the page does not show. */
export function ReadOut({ children }: { children: React.ReactNode }) {
  return <span className={s.readOut}>{children}</span>;
}
