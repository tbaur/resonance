/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Browser calls to /api/v1. Failures become ApiError and keep the request id.
 */

import type {
  ApiErrorBody,
  AppLinks,
  AudioInput,
  BluetoothResponse,
  DeviceSettingsResponse,
  DiagnoseResponse,
  FleetActionResponse,
  FleetFirmwareResponse,
  FleetUpgradeResponse,
  FleetVolumeResponse,
  PlayerStatus,
  Preset,
  QueueResponse,
  SyncEnableResponse,
  UpgradeStatus,
  VersionInfo,
} from './types';
import { ApiError } from './types';
import { REQUEST_HEADER, reportSessionLost } from './auth';
import { isDevicesResponse, isFleetHealth, isRecord, isSyncState } from './shapes';

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

async function request<T>(
  path: string,
  init?: RequestInit & { json?: unknown },
  shape?: Shape<T>,
): Promise<T> {
  const headers = new Headers(init?.headers);
  let body = init?.body;
  if (init?.json !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(init.json);
  }
  headers.set(REQUEST_HEADER, '1');
  const rest: RequestInit & { json?: unknown } = { ...(init ?? {}) };
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
    if (response.status === 204) {
      return undefined as T;
    }
    const parsed: unknown = await response.json();
    if (shape && !shape(parsed)) throw badShape(path);
    return parsed as T;
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
    request<undefined>('/session', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    }),
  links: () => request<AppLinks>('/links'),
  version: () => request<VersionInfo>('/version'),
  listDevices: () => request('/devices', undefined, isDevicesResponse),
  refreshDevices: () => request('/devices/refresh', { method: 'POST' }, isDevicesResponse),
  getDevice: (id: string) => request<PlayerStatus>(`/devices/${seg(id)}`),
  play: (id: string) => request<undefined>(`/devices/${seg(id)}/play`, { method: 'POST' }),
  pause: (id: string) => request<undefined>(`/devices/${seg(id)}/pause`, { method: 'POST' }),
  stop: (id: string) => request<undefined>(`/devices/${seg(id)}/stop`, { method: 'POST' }),
  skip: (id: string) => request<undefined>(`/devices/${seg(id)}/skip`, { method: 'POST' }),
  back: (id: string) => request<undefined>(`/devices/${seg(id)}/back`, { method: 'POST' }),
  toggle: (id: string) => request<undefined>(`/devices/${seg(id)}/toggle`, { method: 'POST' }),
  seek: (id: string, seconds: number) =>
    request<undefined>(`/devices/${seg(id)}/seek`, { method: 'POST', json: { seconds } }),
  setShuffle: (id: string, state: 0 | 1) =>
    request<undefined>(`/devices/${seg(id)}/shuffle`, { method: 'POST', json: { state } }),
  setRepeat: (id: string, state: 0 | 1 | 2) =>
    request<undefined>(`/devices/${seg(id)}/repeat`, { method: 'POST', json: { state } }),
  diagnose: (id: string, init?: RequestInit) =>
    request<DiagnoseResponse>(`/devices/${seg(id)}/diagnose`, { cache: 'no-store', ...init }),
  getSettings: (id: string, pageId: 'audio' | 'player', init?: RequestInit) =>
    request<DeviceSettingsResponse>(`/devices/${seg(id)}/settings/${pageId}`, init),
  setSetting: (id: string, settingId: string, value: string) =>
    request<undefined>(`/devices/${seg(id)}/settings`, {
      method: 'POST',
      json: { id: settingId, value },
    }),
  getUpgrade: (id: string, init?: RequestInit) =>
    request<UpgradeStatus>(`/devices/${seg(id)}/upgrade`, init),
  fleetFirmware: () => request<FleetFirmwareResponse>('/fleet/firmware'),
  fleetUpgrades: () => request<FleetUpgradeResponse>('/fleet/upgrades'),
  getFleetHealth: () => request('/fleet/health', undefined, isFleetHealth),
  reboot: (id: string) => request<undefined>(`/devices/${seg(id)}/reboot`, { method: 'POST' }),
  setVolume: (id: string, level: number) =>
    request<undefined>(`/devices/${seg(id)}/volume`, { method: 'POST', json: { level } }),
  setFleetVolume: (level: number, deviceIds?: string[]) =>
    request<FleetVolumeResponse>('/fleet/volume', {
      method: 'POST',
      json: deviceIds === undefined ? { level } : { level, device_ids: deviceIds },
    }),
  fleetMute: (mute: boolean) =>
    request<FleetActionResponse>('/fleet/mute', { method: 'POST', json: { mute } }),
  fleetPause: () => request<FleetActionResponse>('/fleet/pause', { method: 'POST' }),
  fleetStop: () => request<FleetActionResponse>('/fleet/stop', { method: 'POST' }),
  fleetReboot: () => request<FleetActionResponse>('/fleet/reboot', { method: 'POST' }),
  setMute: (id: string, mute: boolean) =>
    request<undefined>(`/devices/${seg(id)}/mute`, { method: 'POST', json: { mute } }),
  getQueue: (id: string, init?: RequestInit) =>
    request<QueueResponse>(`/devices/${seg(id)}/queue`, init),
  clearQueue: (id: string) =>
    request<undefined>(`/devices/${seg(id)}/queue/clear`, { method: 'POST' }),
  getInputs: (id: string, init?: RequestInit) =>
    request<AudioInput[]>(`/devices/${seg(id)}/inputs`, init),
  setInput: (id: string, input: string) =>
    request<undefined>(`/devices/${seg(id)}/input`, { method: 'POST', json: { input } }),
  getBluetooth: (id: string, init?: RequestInit) =>
    request<BluetoothResponse>(`/devices/${seg(id)}/bluetooth`, init),
  setBluetooth: (id: string, mode: 0 | 1 | 2 | 3) =>
    request<undefined>(`/devices/${seg(id)}/bluetooth`, { method: 'POST', json: { mode } }),
  getPresets: (id: string, init?: RequestInit) =>
    request<Preset[]>(`/devices/${seg(id)}/presets`, init),
  playPreset: (id: string, presetId: string | number) =>
    request<undefined>(`/devices/${seg(id)}/presets/${seg(presetId)}/play`, { method: 'POST' }),
  getSync: () => request('/sync', undefined, isSyncState),
  syncAdd: (masterId: string, slaveId: string) =>
    request<undefined>('/sync/add', {
      method: 'POST',
      json: { master_id: masterId, slave_id: slaveId },
    }),
  syncEnable: (primaryId: string) =>
    request<SyncEnableResponse>('/sync/enable', {
      method: 'POST',
      json: { primary_id: primaryId },
    }),
  syncRemove: (masterId: string, slaveId: string) =>
    request<undefined>('/sync/remove', {
      method: 'POST',
      json: { master_id: masterId, slave_id: slaveId },
    }),
  syncBreak: () => request<FleetActionResponse>('/sync/break', { method: 'POST' }),
  moveQueueItem: (id: string, fromIndex: number, toIndex: number) =>
    request<undefined>(`/devices/${seg(id)}/queue/move`, {
      method: 'POST',
      json: { from_index: fromIndex, to_index: toIndex },
    }),
};
