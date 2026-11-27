/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Runs an action on press, then repeats it while the button is held.
 */

import { useCallback, useEffect, useRef, type MouseEvent, type PointerEvent } from 'react';

type PressRepeatHandlers = {
  onPointerDown: (event: PointerEvent<HTMLButtonElement>) => void;
  onPointerUp: () => void;
  onPointerLeave: () => void;
  onPointerCancel: () => void;
  onContextMenu: (event: MouseEvent) => void;
};

/**
 * Fire `action` immediately, then repeat while held.
 * Uses a ref so rapid steps always see the latest external state.
 *
 * A button that turns `disabled` mid-press (at 0 or 100, or while a write is
 * pending) may never get its own pointerup, so the repeat also stops when
 * `disabled` turns true and on any pointerup, pointercancel, or blur in the window.
 */
export function usePressRepeat(
  action: () => void,
  {
    initialDelayMs = 320,
    repeatMs = 55,
    disabled = false,
  }: { initialDelayMs?: number; repeatMs?: number; disabled?: boolean } = {},
): PressRepeatHandlers {
  const actionRef = useRef(action);
  const delayRef = useRef<number | undefined>(undefined);
  const repeatRef = useRef<number | undefined>(undefined);
  const releaseRef = useRef<(() => void) | undefined>(undefined);

  useEffect(() => {
    actionRef.current = action;
  }, [action]);

  const stop = useCallback(() => {
    if (delayRef.current !== undefined) {
      window.clearTimeout(delayRef.current);
      delayRef.current = undefined;
    }
    if (repeatRef.current !== undefined) {
      window.clearInterval(repeatRef.current);
      repeatRef.current = undefined;
    }
    releaseRef.current?.();
    releaseRef.current = undefined;
  }, []);

  useEffect(() => stop, [stop]);

  useEffect(() => {
    if (disabled) stop();
  }, [disabled, stop]);

  const start = (event: PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    stop();
    actionRef.current();
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
    window.addEventListener('blur', stop);
    releaseRef.current = () => {
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
      window.removeEventListener('blur', stop);
    };
    delayRef.current = window.setTimeout(() => {
      delayRef.current = undefined;
      repeatRef.current = window.setInterval(() => {
        actionRef.current();
      }, repeatMs);
    }, initialDelayMs);
  };

  return {
    onPointerDown: start,
    onPointerUp: stop,
    onPointerLeave: stop,
    onPointerCancel: stop,
    onContextMenu: (event) => {
      event.preventDefault();
    },
  };
}
