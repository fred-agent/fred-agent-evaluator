import { useCallback, useEffect, useRef, useState } from "react";

export type LoadState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: unknown };

/**
 * Loads `load()` whenever it changes (memoize it with useCallback), and again
 * after `pollMs(data)` milliseconds while that returns a number — the host's
 * request bridge has no streaming, so live progress is polled. A poll keeps
 * the current data on screen until the next answer arrives.
 */
export function useLoad<T>(
  load: () => Promise<T>,
  pollMs?: (data: T) => number | null,
) {
  const [state, setState] = useState<LoadState<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const pollRef = useRef(pollMs);
  pollRef.current = pollMs;

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    load().then(
      (data) => {
        if (!active) return;
        setState({ status: "ready", data });
        const delay = pollRef.current?.(data);
        if (delay) timer = setTimeout(() => setAttempt((n) => n + 1), delay);
      },
      (error: unknown) => active && setState({ status: "error", error }),
    );
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [load, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  const retry = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((n) => n + 1);
  }, []);
  return { state, reload, retry };
}
