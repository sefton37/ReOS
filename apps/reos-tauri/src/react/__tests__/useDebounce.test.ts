/**
 * Tests for useDebounce and useDebouncedValue hooks.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useDebounce, useDebouncedValue } from '../hooks/useDebounce';

describe('useDebounce', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('debounces callback invocations', async () => {
    const callback = vi.fn();
    const { result } = renderHook(() => useDebounce(callback, 500));

    // Call multiple times rapidly
    act(() => {
      result.current('call 1');
      result.current('call 2');
      result.current('call 3');
    });

    // Callback should not have been called yet
    expect(callback).not.toHaveBeenCalled();

    // Advance time past debounce delay
    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    // Callback should have been called only once with last args
    expect(callback).toHaveBeenCalledTimes(1);
    expect(callback).toHaveBeenCalledWith('call 3');
  });

  it('uses custom delay', async () => {
    const callback = vi.fn();
    const { result } = renderHook(() => useDebounce(callback, 200));

    act(() => {
      result.current();
    });

    // Not called at 100ms
    await act(async () => {
      vi.advanceTimersByTime(100);
    });
    expect(callback).not.toHaveBeenCalled();

    // Called at 200ms
    await act(async () => {
      vi.advanceTimersByTime(100);
    });
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it('cancels pending timeout on unmount', () => {
    const callback = vi.fn();
    const { result, unmount } = renderHook(() => useDebounce(callback, 500));

    act(() => {
      result.current();
    });

    // Unmount before delay
    unmount();

    // Advance time
    act(() => {
      vi.advanceTimersByTime(500);
    });

    // Callback should not have been called
    expect(callback).not.toHaveBeenCalled();
  });

  it('resets timer on each call', async () => {
    const callback = vi.fn();
    const { result } = renderHook(() => useDebounce(callback, 500));

    act(() => {
      result.current('first');
    });

    // Advance 300ms
    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    // Call again
    act(() => {
      result.current('second');
    });

    // Advance another 300ms (600ms total, but timer was reset)
    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    // Should not have been called yet
    expect(callback).not.toHaveBeenCalled();

    // Advance remaining time
    await act(async () => {
      vi.advanceTimersByTime(200);
    });

    // Now it should be called with second value
    expect(callback).toHaveBeenCalledTimes(1);
    expect(callback).toHaveBeenCalledWith('second');
  });
});

describe('useDebouncedValue', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns initial value immediately', () => {
    const { result } = renderHook(() => useDebouncedValue('initial', 500));
    expect(result.current).toBe('initial');
  });

  it('debounces value changes', async () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 500), {
      initialProps: { value: 'initial' },
    });

    expect(result.current).toBe('initial');

    // Change value
    rerender({ value: 'changed' });

    // Should still be initial
    expect(result.current).toBe('initial');

    // Advance time
    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    // Now should be changed
    expect(result.current).toBe('changed');
  });

  it('resets debounce on rapid value changes', async () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 500), {
      initialProps: { value: 'a' },
    });

    rerender({ value: 'b' });

    await act(async () => {
      vi.advanceTimersByTime(200);
    });

    rerender({ value: 'c' });

    await act(async () => {
      vi.advanceTimersByTime(200);
    });

    // Still 'a' because timers keep resetting
    expect(result.current).toBe('a');

    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    // Now should be 'c'
    expect(result.current).toBe('c');
  });

  it('works with objects', async () => {
    const initial = { count: 0 };
    const updated = { count: 1 };

    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 500), {
      initialProps: { value: initial },
    });

    expect(result.current).toBe(initial);

    rerender({ value: updated });

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(result.current).toBe(updated);
  });
});
