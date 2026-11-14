import React from "react";

import m from "./newGuide.module.css";

/**
 * One labelled row of the New study guide form. `labelId` is the label's id,
 * for a control that has no name of its own to be named by it.
 */
export function Field({
  label, labelId, hint, children,
}: {
  label: string;
  labelId?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={m.field}>
      <span className={m.fieldHead}>
        <span className="label-micro" id={labelId}>{label}</span>
        {hint && <span className={m.fieldHint}>{hint}</span>}
      </span>
      {children}
    </div>
  );
}
