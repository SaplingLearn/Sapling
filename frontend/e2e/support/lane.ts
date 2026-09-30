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
