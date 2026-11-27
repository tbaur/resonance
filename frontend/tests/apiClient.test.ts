/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Structured API errors keep their request id. A 204 is empty. A hung request
 * times out. A caller abort is not a timeout.
 */

import { describe, expect, it, vi, afterEach } from 'vitest';
import { onSessionLost } from '@/api/auth';
import { api } from '@/api/client';
import { ApiError } from '@/api/types';

describe('api client', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('parses structured API errors with request id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        headers: new Headers({ 'X-Request-ID': 'req-abc' }),
        json: () =>
          Promise.resolve({
            error: 'device_not_found',
            message: 'Device is not in the discovered set',
            code: 'device_not_found',
            request_id: 'req-abc',
          }),
      }),
    );

    await expect(api.getDevice('missing')).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(404);
      expect(apiErr.code).toBe('device_not_found');
      expect(apiErr.requestId).toBe('req-abc');
      return true;
    });
  });

  it('falls back when error body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Server Error',
        headers: new Headers(),
        json: () => Promise.reject(new Error('not json')),
      }),
    );

    await expect(api.listDevices()).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.message).toBe('Server Error');
      expect(apiErr.code).toBe('http_error');
      return true;
    });
  });

  it('returns undefined for 204 responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 204,
        headers: new Headers(),
      }),
    );

    await expect(api.toggle('player-1')).resolves.toBeUndefined();
  });

  it('times out when the server never responds', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) => {
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'));
          });
        });
      }),
    );
    const pending = api.listDevices();
    const expectation = expect(pending).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(408);
      expect(apiErr.code).toBe('timeout');
      return true;
    });
    await vi.advanceTimersByTimeAsync(15_000);
    await expectation;
    vi.useRealTimers();
  });

  it('does not treat a caller abort as a timeout', async () => {
    const caller = new AbortController();
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) => {
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'));
          });
        });
      }),
    );
    const pending = api.getQueue('player-1', { signal: caller.signal });
    caller.abort();
    await expect(pending).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(DOMException);
      expect((err as DOMException).name).toBe('AbortError');
      return true;
    });
  });

  const id = 'player-1';
  it.each([
    ['listDevices', () => api.listDevices(), 'GET', '/devices'],
    ['version', () => api.version(), 'GET', '/version'],
    ['links', () => api.links(), 'GET', '/links'],
    ['refreshDevices', () => api.refreshDevices(), 'POST', '/devices/refresh'],
    ['getDevice', () => api.getDevice(id), 'GET', `/devices/${id}`],
    ['play', () => api.play(id), 'POST', `/devices/${id}/play`],
    ['pause', () => api.pause(id), 'POST', `/devices/${id}/pause`],
    ['stop', () => api.stop(id), 'POST', `/devices/${id}/stop`],
    ['skip', () => api.skip(id), 'POST', `/devices/${id}/skip`],
    ['back', () => api.back(id), 'POST', `/devices/${id}/back`],
    ['seek', () => api.seek(id, 42), 'POST', `/devices/${id}/seek`, { seconds: 42 }],
    ['setShuffle', () => api.setShuffle(id, 1), 'POST', `/devices/${id}/shuffle`, { state: 1 }],
    ['setRepeat', () => api.setRepeat(id, 2), 'POST', `/devices/${id}/repeat`, { state: 2 }],
    ['diagnose', () => api.diagnose(id), 'GET', `/devices/${id}/diagnose`],
    ['getSettings', () => api.getSettings(id, 'audio'), 'GET', `/devices/${id}/settings/audio`],
    ['getUpgrade', () => api.getUpgrade(id), 'GET', `/devices/${id}/upgrade`],
    ['fleetFirmware', () => api.fleetFirmware(), 'GET', '/fleet/firmware'],
    ['fleetUpgrades', () => api.fleetUpgrades(), 'GET', '/fleet/upgrades'],
    ['getFleetHealth', () => api.getFleetHealth(), 'GET', '/fleet/health'],
    ['reboot', () => api.reboot(id), 'POST', `/devices/${id}/reboot`],
    ['setVolume', () => api.setVolume(id, 30), 'POST', `/devices/${id}/volume`, { level: 30 }],
    ['setFleetVolume', () => api.setFleetVolume(30), 'POST', '/fleet/volume', { level: 30 }],
    [
      'setFleetVolume scoped',
      () => api.setFleetVolume(30, [id]),
      'POST',
      '/fleet/volume',
      { level: 30, device_ids: [id] },
    ],
    ['fleetMute', () => api.fleetMute(true), 'POST', '/fleet/mute', { mute: true }],
    ['fleetPause', () => api.fleetPause(), 'POST', '/fleet/pause'],
    ['fleetStop', () => api.fleetStop(), 'POST', '/fleet/stop'],
    ['fleetReboot', () => api.fleetReboot(), 'POST', '/fleet/reboot'],
    ['setMute', () => api.setMute(id, false), 'POST', `/devices/${id}/mute`, { mute: false }],
    ['getQueue', () => api.getQueue(id), 'GET', `/devices/${id}/queue`],
    ['clearQueue', () => api.clearQueue(id), 'POST', `/devices/${id}/queue/clear`],
    ['getInputs', () => api.getInputs(id), 'GET', `/devices/${id}/inputs`],
    [
      'setInput',
      () => api.setInput(id, 'spdif-1'),
      'POST',
      `/devices/${id}/input`,
      { input: 'spdif-1' },
    ],
    ['getBluetooth', () => api.getBluetooth(id), 'GET', `/devices/${id}/bluetooth`],
    [
      'setBluetooth',
      () => api.setBluetooth(id, 3),
      'POST',
      `/devices/${id}/bluetooth`,
      { mode: 3 },
    ],
    ['getPresets', () => api.getPresets(id), 'GET', `/devices/${id}/presets`],
    ['playPreset', () => api.playPreset(id, 4), 'POST', `/devices/${id}/presets/4/play`],
    ['getSync', () => api.getSync(), 'GET', '/sync'],
    [
      'syncAdd',
      () => api.syncAdd('lead', id),
      'POST',
      '/sync/add',
      { master_id: 'lead', slave_id: id },
    ],
    ['syncEnable', () => api.syncEnable('lead'), 'POST', '/sync/enable', { primary_id: 'lead' }],
    [
      'syncRemove',
      () => api.syncRemove('lead', id),
      'POST',
      '/sync/remove',
      { master_id: 'lead', slave_id: id },
    ],
    ['syncBreak', () => api.syncBreak(), 'POST', '/sync/break'],
    [
      'moveQueueItem',
      () => api.moveQueueItem(id, 1, 3),
      'POST',
      `/devices/${id}/queue/move`,
      { from_index: 1, to_index: 3 },
    ],
  ] as const)('%s calls %s %s', async (_name, call, method, path, body?: object) => {
    // One body that passes every response shape check.
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: () =>
        Promise.resolve({
          devices: [],
          groups: [],
          standalone_ids: [],
          drops: [],
          first_online: {},
        }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await call();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/v1${path}`);
    expect(init.method ?? 'GET').toBe(method);
    expect(new Headers(init.headers).get('X-Resonance-Request')).toBe('1');
    expect(typeof init.body === 'string' ? JSON.parse(init.body) : init.body).toEqual(body);
  });

  it('posts settings writes without a client-supplied path', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      headers: new Headers(),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.setSetting('player-zone-m', 'channelMode', 'left')).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/devices/player-zone-m/settings',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          id: 'channelMode',
          value: 'left',
        }),
      }),
    );
  });

  it('encodes ids so they stay one path segment', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204, headers: new Headers() });
    vi.stubGlobal('fetch', fetchMock);
    await api.play('../fleet/reboot?x=1');
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/devices/..%2Ffleet%2Freboot%3Fx%3D1/play');
  });

  it('refuses a device list that is not the expected shape', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: () => Promise.resolve({ devices: [{ id: 7 }] }),
      }),
    );
    await expect(api.listDevices()).rejects.toMatchObject({ code: 'bad_response' });
  });

  it('reports a lost session on 401, except from the token form itself', async () => {
    const lost = vi.fn();
    const stop = onSessionLost(lost);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        headers: new Headers(),
        json: () => Promise.resolve({ code: 'unauthorized', message: 'Valid API token required' }),
      }),
    );
    await expect(api.listDevices()).rejects.toMatchObject({ status: 401 });
    expect(lost).toHaveBeenCalledTimes(1);
    await expect(api.openSession('wrong')).rejects.toMatchObject({ status: 401 });
    expect(lost).toHaveBeenCalledTimes(1);
    stop();
  });

  it('takes its abort listener off a long-lived caller signal', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, status: 204, headers: new Headers() }),
    );
    const caller = new AbortController();
    const add = vi.spyOn(caller.signal, 'addEventListener');
    const remove = vi.spyOn(caller.signal, 'removeEventListener');
    await api.play('player-1');
    await api.getQueue('player-1', { signal: caller.signal });
    expect(add).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledTimes(1);
  });

  it('does not send a request whose caller already gave up', async () => {
    const fetchMock = vi.fn((_url: string, init?: RequestInit) =>
      init?.signal?.aborted
        ? Promise.reject(new DOMException('Aborted', 'AbortError'))
        : Promise.resolve({ ok: true, status: 204, headers: new Headers() }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const caller = new AbortController();
    caller.abort();
    await expect(api.getQueue('player-1', { signal: caller.signal })).rejects.toMatchObject({
      name: 'AbortError',
    });
  });
});
