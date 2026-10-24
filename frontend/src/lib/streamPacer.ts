/**
 * Smooths a token stream that arrives in bursts into a steady reveal.
 *
 * Some models deliver a reply in one burst: Claude Sonnet 5.5 sends the text
 * that follows a tool call all at once, after several silent seconds (ADR
 * 0030; the tutor searches course materials on most turns). Rendered raw, the
 * whole reply pops in with no typing. The pacer queues incoming deltas and
 * releases them on a timer instead:
 *
 * - A stream that already arrives at typing speed passes through almost
 *   unchanged; the backlog never grows past one tick's worth.
 * - A burst drains at a rate proportional to the backlog, so a 2,000-char
 *   reply types out in about 1.5 s, and even a very long one stays near 3 s
 *   (the drain time grows with the log of the backlog, not linearly).
 *
 * Timing is measured, not counted: a tick releases what the elapsed time
 * allows, so a background tab, where timers are clamped to about 1 s and
 * `requestAnimationFrame` never fires, still drains at the same rate.
 */

/** Floor rate in chars/s, about what a model that streams normally types. */
const MIN_CHARS_PER_SEC = 600;
/** The backlog decays with this time constant (ms). */
const BACKLOG_TAU_MS = 500;
const TICK_MS = 16;

export interface StreamPacer {
  /** Queue a delta for release. */
  push(delta: string): void;
  /** Resolves once everything pushed so far has been released. */
  drain(): Promise<void>;
  /** Release everything queued right now, synchronously. */
  flush(): void;
}

export function createStreamPacer(
  emit: (text: string) => void,
  now: () => number = () => performance.now(),
): StreamPacer {
  let backlog = "";
  let timer: ReturnType<typeof setTimeout> | null = null;
  let lastTick = 0;
  let waiters: (() => void)[] = [];

  const settle = () => {
    const w = waiters;
    waiters = [];
    for (const resolve of w) resolve();
  };

  const release = (n: number) => {
    let end = Math.min(n, backlog.length);
    // Never cut a surrogate pair in half: the lone half renders as a box.
    const code = backlog.charCodeAt(end - 1);
    if (end < backlog.length && code >= 0xd800 && code <= 0xdbff) end += 1;
    const out = backlog.slice(0, end);
    backlog = backlog.slice(end);
    if (out) emit(out);
  };

  const tick = () => {
    timer = null;
    const t = now();
    const dt = Math.max(t - lastTick, 1);
    lastTick = t;
    const n = Math.max(
      Math.ceil((MIN_CHARS_PER_SEC * dt) / 1000),
      Math.ceil((backlog.length * dt) / BACKLOG_TAU_MS),
    );
    release(n);
    if (backlog) timer = setTimeout(tick, TICK_MS);
    else settle();
  };

  return {
    push(delta) {
      if (!delta) return;
      backlog += delta;
      if (timer === null) {
        lastTick = now();
        timer = setTimeout(tick, TICK_MS);
      }
    },
    drain() {
      if (!backlog && timer === null) return Promise.resolve();
      return new Promise<void>(resolve => waiters.push(resolve));
    },
    flush() {
      if (timer !== null) clearTimeout(timer);
      timer = null;
      release(backlog.length);
      settle();
    },
  };
}
