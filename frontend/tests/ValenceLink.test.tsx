/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * The Valence pill renders when the server has Valence's address.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/api/client';
import { ValenceLink } from '@/components/ValenceLink';

vi.mock('@/api/client', () => ({
  api: { links: vi.fn() },
}));

const links = vi.mocked(api.links);

describe('ValenceLink', () => {
  beforeEach(() => {
    links.mockReset();
  });

  it('links to Valence when the server has its address', async () => {
    links.mockResolvedValue({ valence_url: 'https://valence.example.com' });
    render(<ValenceLink />);
    const link = await screen.findByRole('link', { name: 'Valence' });
    expect(link).toHaveAttribute('href', 'https://valence.example.com');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
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
