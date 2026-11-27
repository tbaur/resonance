/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * The Resonance server's clock, as seen from this browser.
 *
 * Players report `secs_at` in server time. A phone whose clock is a minute off
 * would otherwise move the playhead by that minute.
 */

let offsetMs = 0;

/** Record the server's time (Unix seconds) from a response or event that just arrived. */
export function noteServerTime(serverSeconds: unknown): void {
  if (typeof serverSeconds !== 'number' || !Number.isFinite(serverSeconds)) return;
  offsetMs = serverSeconds * 1000 - Date.now();
}

/** Now, in server time (milliseconds). */
export function serverNow(): number {
  return Date.now() + offsetMs;
}

/** Forget the measured offset. For tests. */
export function resetServerClock(): void {
  offsetMs = 0;
}
