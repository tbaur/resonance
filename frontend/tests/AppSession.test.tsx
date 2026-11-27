/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * No token is built into the page. A 401 asks for one in the browser, and a
 * later 401 (the server's token changed) asks again.
 */

import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '@/App';
import { reportSessionLost } from '@/api/auth';

vi.mock('@/hooks/useLiveFleet', () => ({
  useLiveFleet: () => undefined,
}));

vi.mock('@/components/FleetPage', () => ({
  FleetPage: () => <div>Fleet</div>,
}));

vi.mock('@/components/HousePage', () => ({
  HousePage: () => <div>House</div>,
}));

vi.mock('@/components/PlayerDetailPage', () => ({
  PlayerDetailPage: () => <div>Player</div>,
}));

function respond(status: number) {
  return {
    ok: status < 400,
    status,
    statusText: '',
    headers: new Headers(),
    json: () =>
      Promise.resolve(
        status === 401
          ? { error: 'unauthorized', message: 'Valid API token required', code: 'unauthorized' }
          : { devices: [], discovered_at: null, discovery_method: '' },
      ),
  };
}

function call(fetchMock: ReturnType<typeof vi.fn>, index: number) {
  const [url, init] = fetchMock.mock.calls[index] as [string, RequestInit];
  return {
    url,
    method: init.method ?? 'GET',
    auth: new Headers(init.headers).get('Authorization'),
  };
}

function renderApp() {
  return render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
}

describe('API session', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it('opens the app when the server has no token set, sending no token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(200));
    vi.stubGlobal('fetch', fetchMock);

    renderApp();

    expect(await screen.findByText('Fleet')).toBeInTheDocument();
    expect(call(fetchMock, 0)).toEqual({ url: '/api/v1/devices', method: 'GET', auth: null });
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: 'include' });
  });

  it('asks for a token on a 401, and sends the typed one', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond(401))
      .mockResolvedValueOnce(respond(204));
    vi.stubGlobal('fetch', fetchMock);

    renderApp();

    fireEvent.change(await screen.findByLabelText('API token'), {
      target: { value: ' typed-token ' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    expect(await screen.findByText('Fleet')).toBeInTheDocument();
    expect(call(fetchMock, 1)).toEqual({
      url: '/api/v1/session',
      method: 'POST',
      auth: 'Bearer typed-token',
    });
  });

  it('asks for the token again when the session stops working', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(200)));

    renderApp();
    expect(await screen.findByText('Fleet')).toBeInTheDocument();

    act(() => {
      reportSessionLost();
    });

    expect(await screen.findByLabelText('API token')).toBeInTheDocument();
    expect(screen.queryByText('Fleet')).not.toBeInTheDocument();
  });
});
