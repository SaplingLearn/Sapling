/**
 * The admin feature-flag shapes (#620, ADR 0029): what /api/admin/flags returns
 * per flag, and what its "Check a student" endpoint answers. The calls stay in
 * `@/lib/api` (`adminListFlags`, `adminExplainFlag`, …), which re-exports these.
 */

export type AdminFlagTarget = { target_type: 'user' | 'role'; target_id: string; label: string; variant: string };

/** A variant and the rule that decided it (backend services/feature_flags.py
 *  `Resolution`). `step`: user / role / rollout / default / env_override /
 *  fail_closed, and for a learning-loop flag (#866 K24, learning/gate.py)
 *  kill_switch (`detail` names LEARNING_LOOP_ENABLED) or requires (`detail`
 *  names the flag it needs on, `master` that flag's own answer). */
export type FlagRule = {
  variant: string; step: string; detail: string;
  master?: { key: string; variant: string; step: string; detail: string };
};

export type AdminFlag = {
  key: string; description: string; variants: string[]; client_visible: boolean;
  default_variant: string; rollout_percent: number; rollout_variant: string | null;
  /** The variant SAPLING_FLAG_<KEY> forces on the server, or null. It wins
   *  over every stored setting. */
  env_override?: string | null;
  /** #866 K24: the flag this one acts under for the same student
   *  (`learning_loop` for a learning-loop flag), or null. */
  requires?: string | null;
  /** #866 K24: what every student gets whatever is stored here, and why — the
   *  learning loop's kill switch, or an env override — or null when the
   *  stored settings decide. `only_with` names a flag the answer holds under:
   *  a loop flag's own env override forces it only for students with
   *  `learning_loop` on, and the rest still get its off variant. */
  forced?: (FlagRule & { only_with?: string | null }) | null;
  updated_at: string | null; updated_by: string | null; updated_by_name: string | null;
  targets: AdminFlagTarget[];
};
