/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * The last image stays when the URL goes empty. No image
 * at all shows the empty state.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StickyArt } from '@/components/StickyArt';

describe('StickyArt', () => {
  it('keeps the last image when src goes empty', () => {
    const { rerender } = render(
      <StickyArt src="/api/v1/devices/a/art" empty={<span>empty</span>} />,
    );
    expect(screen.getByRole('presentation')).toHaveAttribute('src', '/api/v1/devices/a/art');
    rerender(<StickyArt src="" empty={<span>empty</span>} />);
    expect(screen.getByRole('presentation')).toHaveAttribute('src', '/api/v1/devices/a/art');
    expect(screen.queryByText('empty')).not.toBeInTheDocument();
  });

  it('shows the empty state when the cover never arrives', () => {
    const { rerender } = render(
      <StickyArt src="/api/v1/devices/a/art?image=one" empty={<span>empty</span>} />,
    );
    fireEvent.error(screen.getByRole('presentation'));
    expect(screen.getByRole('presentation')).toHaveAttribute('src', expect.stringContaining('retry=1'));
    fireEvent.error(screen.getByRole('presentation'));
    expect(screen.getByText('empty')).toBeInTheDocument();

    rerender(<StickyArt src="/api/v1/devices/a/art?image=two" empty={<span>empty</span>} />);
    expect(screen.getByRole('presentation')).toHaveAttribute(
      'src',
      '/api/v1/devices/a/art?image=two',
    );
  });
});
