/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * A wrong token stays on the form. An accepted token opens the app. A silent
 * API says it cannot be reached.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SessionGate } from '@/components/SessionGate';
import { must } from './must';

const listDevices = vi.fn();
const openSession = vi.fn();

vi.mock('@/api/client', () => ({
  api: {
    listDevices: (...args: unknown[]): unknown => listDevices(...args),
    openSession: (...args: unknown[]): unknown => openSession(...args),
  },
}));

async function apiError(status: number) {
  const { ApiError } = await import('@/api/types');
  return new ApiError(status, { error: 'x', message: 'x', code: 'x', request_id: '-' });
}

function renderGate() {
  return render(
    <SessionGate>
      <div>App content</div>
    </SessionGate>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe('SessionGate token form', () => {
  it('explains a wrong token and keeps the form', async () => {
    listDevices.mockRejectedValue(await apiError(401));
    openSession.mockRejectedValue(await apiError(401));
    renderGate();

    const input = await screen.findByLabelText('API token');
    // Focus is applied in an effect after the 401 probe. jsdom 31 can leave
    // the page focused for a turn, so wait instead of asserting immediately.
    await waitFor(() => expect(input).toHaveFocus());
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();

    fireEvent.change(input, { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'That token does not match the one set on the server.',
    );
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(screen.queryByText('App content')).not.toBeInTheDocument();
  });

  it('says when the server cannot be reached during sign-in', async () => {
    listDevices.mockRejectedValue(await apiError(401));
    openSession.mockRejectedValue(new TypeError('Failed to fetch'));
    renderGate();

    fireEvent.change(await screen.findByLabelText('API token'), { target: { value: 'token' } });
    fireEvent.submit(must(screen.getByLabelText('API token').closest('form'), 'token form'));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach Resonance');
  });

  it('shows and hides the token', async () => {
    listDevices.mockRejectedValue(await apiError(401));
    renderGate();

    const input = await screen.findByLabelText('API token');
    expect(input).toHaveAttribute('type', 'password');
    fireEvent.click(screen.getByRole('button', { name: 'Show' }));
    expect(input).toHaveAttribute('type', 'text');
    fireEvent.click(screen.getByRole('button', { name: 'Hide' }));
    expect(input).toHaveAttribute('type', 'password');
  });

  it('opens the app once the token is accepted', async () => {
    listDevices.mockRejectedValue(await apiError(401));
    openSession.mockResolvedValue(undefined);
    renderGate();

    fireEvent.change(await screen.findByLabelText('API token'), { target: { value: 'right' } });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    expect(await screen.findByText('App content')).toBeInTheDocument();
    expect(openSession).toHaveBeenCalledWith('right');
  });
});

describe('SessionGate when the API is down', () => {
  it('retries on request and opens once the API answers', async () => {
    listDevices.mockRejectedValueOnce(await apiError(502)).mockResolvedValue({});
    renderGate();

    fireEvent.click(await screen.findByRole('button', { name: 'Try again now' }));
    expect(await screen.findByText('App content')).toBeInTheDocument();
  });

  it('retries on its own every few seconds', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    listDevices.mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValue({});
    renderGate();

    await screen.findByRole('heading', { name: 'Can’t reach Resonance' });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(await screen.findByText('App content')).toBeInTheDocument();
    expect(listDevices).toHaveBeenCalledTimes(2);
  });
});

describe('SessionGate refusals', () => {
  it('names the fix when the server refuses this host name, instead of retrying', async () => {
    const { ApiError } = await import('@/api/types');
    listDevices.mockRejectedValue(
      new ApiError(400, {
        error: 'host_not_allowed',
        message: 'Host name is not allowed. Add it to RESONANCE_ALLOWED_HOSTS.',
        code: 'host_not_allowed',
        request_id: 'req-1',
      }),
    );
    renderGate();
    expect(
      await screen.findByRole('heading', { name: 'Resonance refused this page' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Host name is not allowed');
    expect(screen.queryByText(/not answering/)).not.toBeInTheDocument();
    expect(screen.getByText('RESONANCE_ALLOWED_HOSTS', { selector: 'code' })).toBeInTheDocument();
  });
});
