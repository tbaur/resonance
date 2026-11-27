/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Steps a volume up or down, including while the button is held.
 */

import { useEffect, useRef } from 'react';
import { usePressRepeat } from '@/hooks/usePressRepeat';

type VolumeNudgeButtonsProps = {
  value: number;
  onChange: (level: number) => void;
  disabled?: boolean;
};

export function VolumeNudgeButtons({ value, onChange, disabled = false }: VolumeNudgeButtonsProps) {
  const levelRef = useRef(value);
  useEffect(() => {
    levelRef.current = value;
  }, [value]);

  const nudge = (delta: number) => {
    const next = Math.max(0, Math.min(100, levelRef.current + delta));
    if (next === levelRef.current) return;
    levelRef.current = next;
    onChange(next);
  };

  const downDisabled = disabled || value <= 0;
  const upDisabled = disabled || value >= 100;
  // Only the 0 and 100 limits end a held press. `disabled` also turns true
  // while the house slider's write is in flight, a few milliseconds into every
  // press, and stopping then would end each hold after one step. A release is
  // caught by the window listeners in usePressRepeat either way.
  const down = usePressRepeat(
    () => {
      nudge(-1);
    },
    { disabled: value <= 0 },
  );
  const up = usePressRepeat(
    () => {
      nudge(1);
    },
    { disabled: value >= 100 },
  );

  return (
    <div className="volume-nudge" role="group" aria-label="Adjust volume">
      <button
        type="button"
        className="btn btn-compact volume-nudge-btn"
        disabled={downDisabled}
        aria-label="Volume down"
        {...down}
      >
        −
      </button>
      <button
        type="button"
        className="btn btn-compact volume-nudge-btn"
        disabled={upDisabled}
        aria-label="Volume up"
        {...up}
      >
        +
      </button>
    </div>
  );
}
