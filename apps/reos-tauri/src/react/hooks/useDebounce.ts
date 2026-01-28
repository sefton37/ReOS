import { useState, useEffect, useRef, useCallback } from 'react';

/**
 * A hook that returns a debounced version of a callback function.
 * The callback will only be invoked after the specified delay has passed
 * since the last invocation.
 *
 * @param callback - The function to debounce
 * @param delay - Delay in milliseconds (default: 500ms)
 * @param flushOnUnmount - If true, executes pending callback on unmount instead of canceling
 * @returns A debounced version of the callback
 */
export function useDebounce<T extends (...args: never[]) => void>(
  callback: T,
  delay: number = 500,
  flushOnUnmount: boolean = false,
): (...args: Parameters<T>) => void {
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const callbackRef = useRef(callback);
  const pendingArgsRef = useRef<Parameters<T> | null>(null);

  // Keep callback ref up to date
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  // Cleanup on unmount - flush or clear based on option
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        // If flushOnUnmount is true and we have pending args, execute immediately
        if (flushOnUnmount && pendingArgsRef.current !== null) {
          callbackRef.current(...pendingArgsRef.current);
        }
      }
    };
  }, [flushOnUnmount]);

  return useCallback(
    (...args: Parameters<T>) => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }

      // Store pending args for potential flush
      pendingArgsRef.current = args;

      timeoutRef.current = setTimeout(() => {
        pendingArgsRef.current = null;  // Clear pending after execution
        callbackRef.current(...args);
      }, delay);
    },
    [delay],
  );
}

/**
 * A hook that debounces a value.
 * Returns the value after it has stopped changing for the specified delay.
 *
 * @param value - The value to debounce
 * @param delay - Delay in milliseconds (default: 500ms)
 * @returns The debounced value
 */
export function useDebouncedValue<T>(value: T, delay: number = 500): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timeout = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => clearTimeout(timeout);
  }, [value, delay]);

  return debouncedValue;
}
