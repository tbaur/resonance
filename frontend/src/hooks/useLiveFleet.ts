/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Holds the server-sent event stream open, applies fleet payloads, and falls
 * back to REST while the stream is down.
 */

import { useEffect, useRef } from 'react';
import type { FleetHealthResponse, PlayerStatus, SyncState } from '@/api/types';
import { useFleetStore } from '@/store/fleetStore';
import { api } from '@/api/client';
import { REQUEST_HEADER, reportSessionLost } from '@/api/auth';
import { isFleetHealth, isPlayerStatus, isRecord, isSyncState } from '@/api/shapes';
import { noteServerTime } from '@/lib/serverClock';

type FleetEvent =
  | {
      type: 'fleet';
      devices: PlayerStatus[];
      discoveredAt: number | null;
      sync: SyncState | null;
      health: FleetHealthResponse | null;
    }
  | { type: 'device'; device: PlayerStatus };

type StreamState = 'connecting' | 'live' | 'reconnecting' | 'offline';

const MAX_RECONNECT_ATTEMPTS = 8;
const OFFLINE_RETRY_MS = 60_000;
/** The server's keepalive interval when its response does not name one. */
const DEFAULT_KEEPALIVE_MS = 15_000;
/**
 * A stream that sends nothing, not even a keepalive, for this many keepalive
 * intervals is dead (a sleeping laptop, a Wi-Fi roam) even though the socket
 * never closed. It is dropped and opened again.
 */
const IDLE_KEEPALIVES = 2.5;

/** The server refused this browser: its session cookie no longer works. */
class StreamUnauthorized extends Error {}

/** No bytes arrived within the idle limit. */
class StreamIdle extends Error {}

function eventHeaders(): Headers {
  return new Headers({
    Accept: 'text/event-stream',
    [REQUEST_HEADER]: '1',
  });
}

/** One server frame as a typed event, or null when it is not one we understand. */
export function parseFleetEvent(raw: string): FleetEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(parsed)) return null;
  noteServerTime(parsed.sent_at);
  const data = parsed.data;
  if (parsed.type === 'device') {
    return isPlayerStatus(data) ? { type: 'device', device: data } : null;
  }
  if (parsed.type !== 'fleet' || !isRecord(data) || !Array.isArray(data.devices)) return null;
  if (!data.devices.every(isPlayerStatus)) return null;
  return {
    type: 'fleet',
    devices: data.devices,
    discoveredAt: typeof data.discovered_at === 'number' ? data.discovered_at : null,
    sync: isSyncState(data.sync) ? data.sync : null,
    health: isFleetHealth(data.health) ? data.health : null,
  };
}

function keepaliveMs(response: Response): number {
  const seconds = Number(response.headers.get('X-Resonance-Keepalive'));
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : DEFAULT_KEEPALIVE_MS;
}

async function readServerEvents(
  response: Response,
  onMessage: (event: FleetEvent) => void,
  signal: AbortSignal,
  idleMs: number,
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = '';
  while (!signal.aborted) {
    let idleTimer: number | undefined;
    const idle = new Promise<never>((_resolve, reject) => {
      idleTimer = window.setTimeout(() => {
        reject(new StreamIdle('no data from the event stream'));
      }, idleMs);
    });
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await Promise.race([reader.read(), idle]);
    } catch (err) {
      if (err instanceof StreamIdle) void reader.cancel().catch(() => undefined);
      throw err;
    } finally {
      window.clearTimeout(idleTimer);
    }
    if (chunk.done) return;
    buffer += decoder.decode(chunk.value, { stream: true });
    let split = buffer.indexOf('\n\n');
    while (split !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const data = frame
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n');
      if (data) {
        const event = parseFleetEvent(data);
        if (event) onMessage(event);
      }
      split = buffer.indexOf('\n\n');
    }
  }
}

function connectWithBackoff(
  onMessage: (event: FleetEvent) => void,
  onState: (state: StreamState) => void,
  signal: AbortSignal,
): void {
  let attempt = 0;
  let timer: number | undefined;
  let stream: AbortController | null = null;

  const cleanup = () => {
    if (timer) window.clearTimeout(timer);
    stream?.abort();
  };
  signal.addEventListener('abort', cleanup);

  const schedule = (delay: number) => {
    timer = window.setTimeout(open, delay);
  };

  const open = () => {
    if (signal.aborted) return;
    onState(attempt === 0 ? 'connecting' : 'reconnecting');
    stream = new AbortController();
    const linked = stream;
    // A function, so each check reads the signals now, after the awaits above it.
    const stopped = () => signal.aborted || linked.signal.aborted;
    void (async () => {
      try {
        const response = await fetch('/api/v1/events', {
          headers: eventHeaders(),
          credentials: 'include',
          signal: linked.signal,
        });
        if (stopped()) return;
        if (response.status === 401) throw new StreamUnauthorized();
        if (!response.ok) throw new Error(String(response.status));
        attempt = 0;
        onState('live');
        const idleMs = keepaliveMs(response) * IDLE_KEEPALIVES;
        await readServerEvents(response, onMessage, linked.signal, idleMs);
        if (stopped()) return;
        throw new Error('stream closed');
      } catch (err) {
        if (stopped()) return;
        if (err instanceof StreamUnauthorized) {
          // Retrying cannot help: the browser has to sign in again.
          onState('offline');
          reportSessionLost();
          return;
        }
        linked.abort();
        attempt += 1;
        if (attempt >= MAX_RECONNECT_ATTEMPTS) {
          onState('offline');
          attempt = 0;
          schedule(OFFLINE_RETRY_MS);
          return;
        }
        onState('reconnecting');
        const delay = Math.min(30_000, 1000 * 2 ** (attempt - 1)) + Math.random() * 250;
        schedule(delay);
      }
    })();
  };

  open();
}

export function useLiveFleet(): void {
  const setFleet = useFleetStore((s) => s.setFleet);
  const upsertDevice = useFleetStore((s) => s.upsertDevice);
  const setConnection = useFleetStore((s) => s.setConnection);
  const setSync = useFleetStore((s) => s.setSync);
  const setHealth = useFleetStore((s) => s.setHealth);
  const load = useFleetStore((s) => s.load);
  const pollFallback = useRef<number | undefined>(undefined);

  useEffect(() => {
    void load();
    const controller = new AbortController();

    connectWithBackoff(
      (event) => {
        if (event.type === 'device') {
          upsertDevice(event.device);
          return;
        }
        setFleet(event.devices, event.discoveredAt);
        if (event.sync) {
          setSync(event.sync);
        } else {
          void api
            .getSync()
            .then(setSync)
            .catch(() => undefined);
        }
        if (event.health) setHealth(event.health);
      },
      (state) => {
        setConnection(state);
        if (state === 'reconnecting' || state === 'offline') {
          if (!pollFallback.current) {
            pollFallback.current = window.setInterval(() => {
              void load();
            }, 5000);
          }
        } else if (state === 'live' && pollFallback.current) {
          window.clearInterval(pollFallback.current);
          pollFallback.current = undefined;
        }
      },
      controller.signal,
    );

    return () => {
      controller.abort();
      if (pollFallback.current) window.clearInterval(pollFallback.current);
    };
  }, [load, setConnection, setFleet, setHealth, setSync, upsertDevice]);
}
