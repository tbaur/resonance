/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * The Valence pill renders when the server has Valence's address.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/api/client';
import { ValenceLink } from '@/components/ValenceLink';

vi.mock('@/api/client', () => ({
  api: { links: vi.fn() },
}));

const links = vi.mocked(api.links);
const VALENCE = 'https://valence.example.com';

function displayMode(standalone: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: standalone && query === '(display-mode: standalone)',
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    })),
  );
}

function clickLink() {
  const link = screen.getByRole('link', { name: 'Valence' });
  const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
  link.dispatchEvent(event);
  return event;
}

describe('ValenceLink', () => {
  const open = vi.fn(() => ({ opener: window }) as unknown as Window);

  beforeEach(() => {
    links.mockReset();
    open.mockClear();
    vi.stubGlobal('open', open);
    displayMode(false);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(navigator, 'standalone');
  });

  it('links to Valence when the server has its address', async () => {
    links.mockResolvedValue({ valence_url: VALENCE });
    render(<ValenceLink />);
    const link = await screen.findByRole('link', { name: 'Valence' });
    expect(link).toHaveAttribute('href', VALENCE);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('opens Valence in another window of the Mac Dock app', async () => {
    displayMode(true);
    links.mockResolvedValue({ valence_url: VALENCE });
    render(<ValenceLink />);
    await screen.findByRole('link', { name: 'Valence' });
    const event = clickLink();
    expect(open).toHaveBeenCalledExactlyOnceWith(VALENCE, 'resonance-valence');
    expect(event.defaultPrevented).toBe(true);
    expect(open.mock.results[0]?.value.opener).toBeNull();
  });

  it('keeps a normal browser tab on the link itself', async () => {
    links.mockResolvedValue({ valence_url: VALENCE });
    render(<ValenceLink />);
    await screen.findByRole('link', { name: 'Valence' });
    const event = clickLink();
    expect(open).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it('leaves an iPhone home-screen app on the link itself', async () => {
    displayMode(true);
    Object.defineProperty(navigator, 'standalone', { configurable: true, value: true });
    links.mockResolvedValue({ valence_url: VALENCE });
    render(<ValenceLink />);
    await screen.findByRole('link', { name: 'Valence' });
    clickLink();
    expect(open).not.toHaveBeenCalled();
  });

  it.each([
    ['no address', () => Promise.resolve({ valence_url: '' })],
    ['an address that is not a web page', () => Promise.resolve({ valence_url: 'javascript:x' })],
    ['a failed request', () => Promise.reject(new Error('offline'))],
  ])('shows nothing for %s', async (_case, answer) => {
    links.mockImplementation(answer);
    const { container } = render(<ValenceLink />);
    await waitFor(() => expect(links).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
