/**
 * The E2E lane (PKG-14b, spec §11.4) — ONE parse, the spec §7 post-launch one:
 * unset / "" / anything else → the default lane (the loop for every student);
 * false / 0 / off / no (any case, whitespace ignored) → the kill-switch lane
 * (the legacy Learn screen, tutor and Study UI; /api/learn/loop/* 404s). Every
 * lane guard uses this — never a raw string compare. scripts/e2e-up.sh refuses a
 * LEARNING_LOOP_ENABLED line in backend/.env, and global-setup.ts asserts the
 * running stack agrees with this value.
 */
export const killSwitchLane = ["false", "0", "off", "no"].includes(
  (process.env.LEARNING_LOOP_ENABLED ?? "").trim().toLowerCase(),
);

/**
 * The flag-off lane: the kill switch NOT thrown, but every student's
 * `learning_loop` flag forced off through its env override
 * (SAPLING_FLAG_LEARNING_LOOP=off, parsed as services/feature_flags.py
 * ::env_override does: trimmed, any case). That is production's default — the
 * flag ships off — and the loop is off for each student exactly as under the
 * kill switch (learning/gate.py). scripts/e2e-up.sh forces the flag on unless
 * the caller exported a value.
 */
export const flagOffLane = (process.env.SAPLING_FLAG_LEARNING_LOOP ?? "").trim().toLowerCase() === "off";

/**
 * The loop is off for every seeded student: the kill-switch lane OR the
 * flag-off lane. Every "loop path" guard uses this; `killSwitchLane` stays for
 * what only the kill switch itself does (the kill-switch-only legacy-screen
 * test).
 */
export const loopOffLane = killSwitchLane || flagOffLane;
