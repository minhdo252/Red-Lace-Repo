"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** A tiny finite-state-machine helper for the module phase flows. */
export function usePhase<T extends string>(initial: T) {
  const [phase, setPhase] = useState<T>(initial);
  const reset = useCallback(() => setPhase(initial), [initial]);
  return { phase, setPhase, reset };
}

/** A running elapsed timer (seconds). Start/stop/reset controlled. */
export function useTimer(running: boolean) {
  const [seconds, setSeconds] = useState(0);
  const ref = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (running) {
      ref.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    }
    return () => {
      if (ref.current) clearInterval(ref.current);
    };
  }, [running]);

  const reset = useCallback(() => setSeconds(0), []);
  return { seconds, reset };
}

export type ProgressStep = { label: string };

/**
 * Steps through labelled analysis stages over `totalMs`, exposing the current
 * step index, label, and a smooth 0–100 percentage. Calls onDone when finished.
 */
export function useFakeProgress(
  steps: ProgressStep[],
  totalMs: number,
  active: boolean,
  onDone?: () => void,
) {
  const [index, setIndex] = useState(0);
  const [percent, setPercent] = useState(0);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    if (!active) {
      setIndex(0);
      setPercent(0);
      return;
    }
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const elapsed = now - start;
      const p = Math.min(100, (elapsed / totalMs) * 100);
      setPercent(p);
      const i = Math.min(steps.length - 1, Math.floor((p / 100) * steps.length));
      setIndex(i);
      if (p < 100) {
        raf = requestAnimationFrame(tick);
      } else {
        doneRef.current?.();
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active, totalMs, steps.length]);

  return { index, percent, label: steps[index]?.label ?? "" };
}

/** Reveal an array of items one at a time on a stagger (for chat/list drips). */
export function useStaggeredReveal<T>(items: T[], active: boolean, stepMs = 650) {
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!active) {
      setCount(0);
      return;
    }
    if (count >= items.length) return;
    const t = setTimeout(() => setCount((c) => c + 1), count === 0 ? 250 : stepMs);
    return () => clearTimeout(t);
  }, [active, count, items.length, stepMs]);

  return items.slice(0, count);
}
