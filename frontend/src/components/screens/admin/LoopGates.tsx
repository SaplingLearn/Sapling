"use client";

/**
 * Admin learning-loop: spec §10's gates and what each one counted. Admin only —
 * nothing here reaches a student. Reads GET /api/admin/analytics/learning-loop
 * (services/admin/analytics/learning_loop.py::learning_loop_report).
 *
 * A gate is pass / fail, or "inconclusive" (null) when nothing in the range
 * carries its signal, never a silent pass (#866 K56). Beside the chips, every
 * gate's n (#866 K57): the zero-reveal gate counts the open questions a SERVED
 * turn answered (spec §13 A90); leaks caught on the active item were cut before
 * serving and never turn it red; a turn served unscanned (its open questions
 * could not be read) is one the gate cannot see into, so the panel says so
 * whenever there is one. Those turns fail closed: every question posed before
 * them is graded as assisted.
 */

import React from "react";
import type { LearningLoopKpisData } from "@/lib/types";

const muted: React.CSSProperties = { color: "var(--text-muted)", fontSize: 13, margin: 0 };

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

/** A §10 gate: pass / fail, or "inconclusive" (null) — never a silent pass. */
function GateChip({ label, ok, testid }: { label: string; ok: boolean | null; testid: string }) {
  const state = ok == null ? "inconclusive" : ok ? "pass" : "fail";
  return (
    <span data-testid={testid} data-state={state} className={`chip ${ok === false ? "chip--err" : ""}`}
      title={ok == null ? "No step carries the signal yet in this range." : undefined}>
      {label}: {state}
    </span>
  );
}

export function LoopGates({ d }: { d: LearningLoopKpisData }) {
  const unscanned = d.unscanned_turns;
  return (
    <div style={{ display: "grid", gap: 8, marginBottom: 16 }}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <GateChip label="Zero served reveals" ok={d.gates.zero_leaks} testid="admin-loop-gate-leaks" />
        <GateChip label="Ceiling compliance ≥ 95%" ok={d.gates.ceiling_compliance_ok} testid="admin-loop-gate-ceiling" />
        <GateChip label="Earnest-revise ≤ 5%" ok={d.gates.earnest_revise_ok} testid="admin-loop-gate-earnest" />
      </div>
      <p data-testid="admin-loop-gate-counts" style={muted}>
        {`${plural(d.served_reveals, "served reveal")} · ${plural(d.caught_leaks, "leak")} caught and cut before serving · ${plural(unscanned, "turn")} served unscanned · ceiling compliance over ${plural(d.ceiling_compliance.steps, "step")}`}
      </p>
      {unscanned > 0 && (
        <p data-testid="admin-loop-gate-unscanned" role="note" style={{ ...muted, color: "var(--text)" }}>
          {`${plural(unscanned, "tutor turn")} ${unscanned === 1 ? "was" : "were"} served without the answer scan: the open questions could not be read, so "Zero served reveals" cannot vouch for what ${unscanned === 1 ? "it" : "they"} said. Every question posed before ${unscanned === 1 ? "it" : "them"} is graded as assisted.`}
        </p>
      )}
    </div>
  );
}
