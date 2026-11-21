"use client";
/**
 * A ref that always holds the newest value of a prop or callback.
 *
 * The notes editor attaches its listeners to the DOM once and keeps them for
 * the life of the page — re-binding them on every render would drop a drag
 * mid-gesture. Those listeners therefore read their callbacks through this
 * rather than closing over them.
 *
 * The write happens in `useInsertionEffect`, which React runs before layout
 * effects and before the browser can fire anything: assigning during render
 * is what React 19's lint forbids, and a plain `useEffect` would leave the
 * ref one render stale for a listener that fires in between.
 */
import React from "react";

export function useLatest<T>(value: T): React.RefObject<T> {
  const ref = React.useRef(value);
  React.useInsertionEffect(() => { ref.current = value; }, [value]);
  return ref as React.RefObject<T>;
}
