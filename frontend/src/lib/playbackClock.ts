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
 * track: a live stream, shown as "Live", or a skip whose length has not arrived.
 */
export function showsPlaybackBar(
  device: Pick<PlayerStatus, 'state' | 'secs' | 'totlen' | 'track'>,
): boolean {
  if (device.totlen > 0) return true;
  return device.state !== 'stop' && (device.secs > 0 || device.track.trim() !== '');
}

/**
 * `secs` as of `nowMs`. The server can hand over a reading taken long ago,
 * such as after a page reload, because a long-poll only answers on a change.
 * A live stream shows no time, so its reading stays as sent.
 */
export function currentSecs(
  device: Pick<PlayerStatus, 'state' | 'secs' | 'secs_at' | 'totlen'>,
  nowMs: number,
): number {
  if (
    device.secs_at == null ||
    device.totlen <= 0 ||
    (device.state !== 'play' && device.state !== 'stream')
  ) {
    return device.secs;
  }
  return device.secs + Math.max(0, Math.floor(nowMs / 1000 - device.secs_at));
}

export function playbackProgress(secs: number, totlen: number): number {
  if (totlen <= 0) return 0;
  return Math.min(1, Math.max(0, secs / totlen));
}
