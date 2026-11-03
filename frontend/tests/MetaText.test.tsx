/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 */

import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MetaText } from '@/components/MetaText';

describe('MetaText', () => {
  it('wraps each separator in a dimmed span and keeps the full text', () => {
    const { container } = render(<MetaText text="Apple Music | AAC 256 kbps | play" />);
    expect(container.textContent).toBe('Apple Music | AAC 256 kbps | play');
    expect(container.querySelectorAll('.meta-sep')).toHaveLength(2);
  });

  it('renders a line without separators as plain text', () => {
    const { container } = render(<MetaText text="Spotify" />);
    expect(container.textContent).toBe('Spotify');
    expect(container.querySelector('.meta-sep')).toBeNull();
  });

  it('dims a leading separator', () => {
    const { container } = render(<MetaText text=" | up to date" />);
    expect(container.textContent).toBe(' | up to date');
    expect(container.querySelectorAll('.meta-sep')).toHaveLength(1);
  });
});
