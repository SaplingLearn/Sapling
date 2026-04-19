"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface ConfirmHandle {
  armed: boolean;
  trigger: () => void;
  reset: () => void;
}

export function useConfirm(onConfirm: () => void, timeoutMs: number = 3000): ConfirmHandle {
  const [armed, setArmed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reset = useCallback(() => {
    setArmed(false);
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  const trigger = useCallback(() => {
    if (armed) {
      reset();
      onConfirm();
      return;
    }
    setArmed(true);
    timer.current = setTimeout(() => setArmed(false), timeoutMs);
  }, [armed, onConfirm, reset, timeoutMs]);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  return { armed, trigger, reset };
}
