import React from "react";

import m from "./newGuide.module.css";

/** One labelled row of the New study guide form. */
export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className={m.field}>
      <span className={m.fieldHead}>
        <span className="label-micro">{label}</span>
        {hint && <span className={m.fieldHint}>{hint}</span>}
      </span>
      {children}
    </div>
  );
}
