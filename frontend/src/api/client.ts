/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Browser calls to /api/v1. Failures become ApiError and keep the request id.
 */

import type { ApiErrorBody } from './types';
import { ApiError } from './types';
import { REQUEST_HEADER, reportSessionLost } from './auth';
import {
  isAppLinks,
  isAudioInputs,
  isBluetooth,
  isDeviceSettings,
  isDevicesResponse,
  isDiagnose,
  isFleetAction,
  isFleetFirmware,
  isFleetHealth,
  isFleetUpgrades,
  isFleetVolume,
  isPlayerStatus,
  isPresets,
  isQueue,
  isRecord,
  isSyncEnable,
  isSyncState,
  isUpgradeStatus,
  isVersionInfo,
} from './shapes';

const BASE = '/api/v1';
const FETCH_TIMEOUT_MS = 15_000;

function stringField(body: Record<string, unknown>, key: string): string {
  const value = body[key];
  return typeof value === 'string' ? value : '';
}

/** The server's error envelope, or a generic one when the body is not that shape. */
async function parseError(response: Response): Promise<ApiError> {
  const fallback: ApiErrorBody = {
    error: 'http_error',
    message: response.statusText || 'Request failed',
    code: 'http_error',
    request_id: response.headers.get('X-Request-ID') ?? '-',
  };
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return new ApiError(response.status, fallback);
  }
  if (!isRecord(body)) return new ApiError(response.status, fallback);
  return new ApiError(response.status, {
    error: stringField(body, 'error') || fallback.error,
    message: stringField(body, 'message') || fallback.message,
    code: stringField(body, 'code') || fallback.code,
    request_id: stringField(body, 'request_id') || fallback.request_id,
  });
}

/**
 * A signal that aborts when either input does. The listeners come off as soon
 * as one fires or `release` runs, so a long-lived caller signal does not
 * collect one listener per request.
 */
function abortWhenEither(
  left: AbortSignal,
  right: AbortSignal,
): { signal: AbortSignal; release: () => void } {
  const merged = new AbortController();
  const abort = () => {
    merged.abort();
  };
  if (left.aborted || right.aborted) {
    abort();
    return { signal: merged.signal, release: () => undefined };
  }
  const release = () => {
    left.removeEventListener('abort', abort);
    right.removeEventListener('abort', abort);
  };
  left.addEventListener('abort', abort, { once: true });
  right.addEventListener('abort', abort, { once: true });
  merged.signal.addEventListener('abort', release, { once: true });
  return { signal: merged.signal, release };
}

function timeoutError(): ApiError {
  return new ApiError(408, {
    error: 'timeout',
    message: 'Request timed out',
    code: 'timeout',
    request_id: '-',
  });
}

/** Checks that a JSON body has the shape the caller expects, before it is used. */
type Shape<T> = (body: unknown) => body is T;

function badShape(path: string): ApiError {
  return new ApiError(502, {
    error: 'bad_response',
    message: `Unexpected response from ${path}`,
    code: 'bad_response',
    request_id: '-',
  });
}

/** One path segment. An id is data, so it must not add a segment or a query. */
function seg(value: string | number): string {
  return encodeURIComponent(String(value));
}

/** The shape for endpoints that answer 204: any body is ignored. */
const NO_BODY = 'no-body';

type RequestInitWithJson = RequestInit & { json?: unknown };

/**
 * One API call. Every JSON answer is checked against `shape` before the caller
 * sees it, so a payload that is not what the views expect fails here.
 */
function request(
  path: string,
  init: RequestInitWithJson | undefined,
  shape: typeof NO_BODY,
): Promise<undefined>;
function request<T>(
  path: string,
  init: RequestInitWithJson | undefined,
  shape: Shape<T>,
): Promise<T>;
async function request(
  path: string,
  init: RequestInitWithJson | undefined,
  shape: Shape<unknown> | typeof NO_BODY,
): Promise<unknown> {
  const headers = new Headers(init?.headers);
  let body = init?.body;
  if (init?.json !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(init.json);
  }
  headers.set(REQUEST_HEADER, '1');
  const rest: RequestInitWithJson = { ...(init ?? {}) };
  delete rest.json;
  const timeoutController = new AbortController();
  const timeoutId = window.setTimeout(() => {
    timeoutController.abort();
  }, FETCH_TIMEOUT_MS);
  const userSignal = rest.signal ?? undefined;
  const merged = userSignal ? abortWhenEither(userSignal, timeoutController.signal) : undefined;
  const signal = merged ? merged.signal : timeoutController.signal;
  try {
    const response = await fetch(`${BASE}${path}`, {
      ...rest,
      headers,
      body,
      credentials: 'include',
      signal,
    });
    if (!response.ok) {
      // The session form reports its own wrong token; anything else means the
      // cookie stopped working and the browser must sign in again.
      if (response.status === 401 && path !== '/session') reportSessionLost();
      throw await parseError(response);
    }
    if (shape === NO_BODY) return undefined;
    const parsed: unknown = response.status === 204 ? undefined : await response.json();
    if (!shape(parsed)) throw badShape(path);
    return parsed;
  } catch (err) {
    if (err instanceof ApiError) {
      throw err;
    }
    if (err instanceof DOMException && err.name === 'AbortError') {
      // Caller cancelled (unmount / newer control) — not a server timeout.
      if (userSignal?.aborted) throw err;
      throw timeoutError();
    }
    throw err;
  } finally {
    window.clearTimeout(timeoutId);
    merged?.release();
  }
}

export const api = {
  /** Trade an API token for the HttpOnly session cookie. */
  openSession: (token: string) =>
    request(
      '/session',
      {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      },
      NO_BODY,
    ),
  links: () => request('/links', undefined, isAppLinks),
  version: () => request('/version', undefined, isVersionInfo),
  listDevices: () => request('/devices', undefined, isDevicesResponse),
  refreshDevices: () => request('/devices/refresh', { method: 'POST' }, isDevicesResponse),
  getDevice: (id: string) => request(`/devices/${seg(id)}`, undefined, isPlayerStatus),
  play: (id: string) => request(`/devices/${seg(id)}/play`, { method: 'POST' }, NO_BODY),
  pause: (id: string) => request(`/devices/${seg(id)}/pause`, { method: 'POST' }, NO_BODY),
  stop: (id: string) => request(`/devices/${seg(id)}/stop`, { method: 'POST' }, NO_BODY),
  skip: (id: string) => request(`/devices/${seg(id)}/skip`, { method: 'POST' }, NO_BODY),
  back: (id: string) => request(`/devices/${seg(id)}/back`, { method: 'POST' }, NO_BODY),
  toggle: (id: string) => request(`/devices/${seg(id)}/toggle`, { method: 'POST' }, NO_BODY),
  seek: (id: string, seconds: number) =>
    request(`/devices/${seg(id)}/seek`, { method: 'POST', json: { seconds } }, NO_BODY),
  setShuffle: (id: string, state: 0 | 1) =>
    request(`/devices/${seg(id)}/shuffle`, { method: 'POST', json: { state } }, NO_BODY),
  setRepeat: (id: string, state: 0 | 1 | 2) =>
    request(`/devices/${seg(id)}/repeat`, { method: 'POST', json: { state } }, NO_BODY),
  diagnose: (id: string, init?: RequestInit) =>
    request(`/devices/${seg(id)}/diagnose`, { cache: 'no-store', ...init }, isDiagnose),
  getSettings: (id: string, pageId: 'audio' | 'player', init?: RequestInit) =>
    request(`/devices/${seg(id)}/settings/${pageId}`, init, isDeviceSettings),
  setSetting: (id: string, settingId: string, value: string) =>
    request(
      `/devices/${seg(id)}/settings`,
      {
        method: 'POST',
        json: { id: settingId, value },
      },
      NO_BODY,
    ),
  getUpgrade: (id: string, init?: RequestInit) =>
    request(`/devices/${seg(id)}/upgrade`, init, isUpgradeStatus),
  fleetFirmware: () => request('/fleet/firmware', undefined, isFleetFirmware),
  fleetUpgrades: () => request('/fleet/upgrades', undefined, isFleetUpgrades),
  getFleetHealth: () => request('/fleet/health', undefined, isFleetHealth),
  reboot: (id: string) => request(`/devices/${seg(id)}/reboot`, { method: 'POST' }, NO_BODY),
  setVolume: (id: string, level: number) =>
    request(`/devices/${seg(id)}/volume`, { method: 'POST', json: { level } }, NO_BODY),
  setFleetVolume: (level: number, deviceIds?: string[]) =>
    request(
      '/fleet/volume',
      {
        method: 'POST',
        json: deviceIds === undefined ? { level } : { level, device_ids: deviceIds },
      },
      isFleetVolume,
    ),
  fleetMute: (mute: boolean) =>
    request('/fleet/mute', { method: 'POST', json: { mute } }, isFleetAction),
  fleetPause: () => request('/fleet/pause', { method: 'POST' }, isFleetAction),
  fleetStop: () => request('/fleet/stop', { method: 'POST' }, isFleetAction),
  fleetReboot: () => request('/fleet/reboot', { method: 'POST' }, isFleetAction),
  setMute: (id: string, mute: boolean) =>
    request(`/devices/${seg(id)}/mute`, { method: 'POST', json: { mute } }, NO_BODY),
  getQueue: (id: string, init?: RequestInit) => request(`/devices/${seg(id)}/queue`, init, isQueue),
  clearQueue: (id: string) =>
    request(`/devices/${seg(id)}/queue/clear`, { method: 'POST' }, NO_BODY),
  getInputs: (id: string, init?: RequestInit) =>
    request(`/devices/${seg(id)}/inputs`, init, isAudioInputs),
  setInput: (id: string, input: string) =>
    request(`/devices/${seg(id)}/input`, { method: 'POST', json: { input } }, NO_BODY),
  getBluetooth: (id: string, init?: RequestInit) =>
    request(`/devices/${seg(id)}/bluetooth`, init, isBluetooth),
  setBluetooth: (id: string, mode: 0 | 1 | 2 | 3) =>
    request(`/devices/${seg(id)}/bluetooth`, { method: 'POST', json: { mode } }, NO_BODY),
  getPresets: (id: string, init?: RequestInit) =>
    request(`/devices/${seg(id)}/presets`, init, isPresets),
  playPreset: (id: string, presetId: string | number) =>
    request(`/devices/${seg(id)}/presets/${seg(presetId)}/play`, { method: 'POST' }, NO_BODY),
  getSync: () => request('/sync', undefined, isSyncState),
  syncAdd: (masterId: string, slaveId: string) =>
    request(
      '/sync/add',
      {
        method: 'POST',
        json: { master_id: masterId, slave_id: slaveId },
      },
      NO_BODY,
    ),
  syncEnable: (primaryId: string) =>
    request(
      '/sync/enable',
      {
        method: 'POST',
        json: { primary_id: primaryId },
      },
      isSyncEnable,
    ),
  syncRemove: (masterId: string, slaveId: string) =>
    request(
      '/sync/remove',
      {
        method: 'POST',
        json: { master_id: masterId, slave_id: slaveId },
      },
      NO_BODY,
    ),
  syncBreak: () => request('/sync/break', { method: 'POST' }, isFleetAction),
  moveQueueItem: (id: string, fromIndex: number, toIndex: number) =>
    request(
      `/devices/${seg(id)}/queue/move`,
      {
        method: 'POST',
        json: { from_index: fromIndex, to_index: toIndex },
      },
      NO_BODY,
    ),
};
