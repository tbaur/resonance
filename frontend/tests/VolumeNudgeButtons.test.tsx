/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Volume steps up and down, and stops at 0 and at 100.
 */

import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { VolumeNudgeButtons } from '@/components/VolumeNudgeButtons';

describe('VolumeNudgeButtons', () => {
  it('nudges volume up and down', () => {
    const onChange = vi.fn();
    render(<VolumeNudgeButtons value={20} onChange={onChange} />);
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Volume up' }), { button: 0 });
    expect(onChange).toHaveBeenCalledWith(21);
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Volume down' }), { button: 0 });
    expect(onChange).toHaveBeenCalledWith(20);
  });

  it('disables down at zero and up at 100', () => {
    const { rerender } = render(<VolumeNudgeButtons value={0} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Volume down' })).toBeDisabled();
    rerender(<VolumeNudgeButtons value={100} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Volume up' })).toBeDisabled();
  });

  describe('held', () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    it('stops repeating when the button turns disabled mid-press', () => {
      vi.useFakeTimers();
      const onChange = vi.fn();
      const { rerender } = render(<VolumeNudgeButtons value={98} onChange={onChange} />);
      fireEvent.pointerDown(screen.getByRole('button', { name: 'Volume up' }), { button: 0 });
      // Reaching 100 disables the button, which then gets no pointerup of its own.
      rerender(<VolumeNudgeButtons value={100} onChange={onChange} />);
      const calls = onChange.mock.calls.length;
      act(() => {
        vi.advanceTimersByTime(2000);
      });
      expect(onChange.mock.calls.length).toBe(calls);
    });

    it('keeps repeating while a write in flight disables the buttons', () => {
      vi.useFakeTimers();
      const onChange = vi.fn();
      const { rerender } = render(<VolumeNudgeButtons value={20} onChange={onChange} />);
      fireEvent.pointerDown(screen.getByRole('button', { name: 'Volume up' }), { button: 0 });
      // The house slider sets `pending` about 80 ms into the press.
      rerender(<VolumeNudgeButtons value={21} onChange={onChange} disabled />);
      act(() => {
        vi.advanceTimersByTime(600);
      });
      expect(onChange.mock.calls.length).toBeGreaterThan(2);
    });

    it('stops repeating on a pointerup anywhere in the window', () => {
      vi.useFakeTimers();
      const onChange = vi.fn();
      render(<VolumeNudgeButtons value={20} onChange={onChange} />);
      fireEvent.pointerDown(screen.getByRole('button', { name: 'Volume up' }), { button: 0 });
      act(() => {
        vi.advanceTimersByTime(400);
      });
      fireEvent.pointerUp(window);
      const calls = onChange.mock.calls.length;
      act(() => {
        vi.advanceTimersByTime(2000);
      });
      expect(onChange.mock.calls.length).toBe(calls);
    });
  });
});
