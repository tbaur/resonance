/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Playhead position between polls. A large jump is a seek, not jitter.
 */

import type { PlayerStatus } from '@/api/types';

/** Drift larger than this (seconds) is a seek/skip, not poll jitter. */
export const PLAYBACK_SNAP_SECS = 1.75;

export function playbackPosition(
  originSecs: number,
  originAt: number,
  now: number,
  playing: boolean,
): number {
  if (!playing) return Math.max(0, originSecs);
  return Math.max(0, originSecs + (now - originAt) / 1000);
}

export function clampPlayback(secs: number, totlen: number): number {
  if (totlen > 0) return Math.min(Math.max(0, secs), totlen);
  return Math.max(0, secs);
}

export function shouldSnapPlayback(predicted: number, incoming: number): boolean {
  return Math.abs(predicted - incoming) >= PLAYBACK_SNAP_SECS;
}

/**
 * A track with a length gets the bar. So does anything else that is playing a
 * track or reports time played: a live stream, whose time BluOS counts from when
 * the station started, or a skip whose length has not arrived yet.
 */
export function showsPlaybackBar(
  device: Pick<PlayerStatus, 'state' | 'secs' | 'totlen' | 'track'>,
): boolean {
  if (device.totlen > 0) return true;
  return device.state !== 'stop' && (device.secs > 0 || device.track.trim() !== '');
}

export function playbackProgress(secs: number, totlen: number): number {
  if (totlen <= 0) return 0;
  return Math.min(1, Math.max(0, secs / totlen));
}
