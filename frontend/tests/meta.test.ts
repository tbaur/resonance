/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Meta parts join with a slash.
 */

import { describe, expect, it } from 'vitest';
import { META_SEP, artistAlbumLine, joinMeta } from '@/lib/meta';

describe('artistAlbumLine', () => {
  it('joins artist and album', () => {
    expect(artistAlbumLine('Song', 'Artist', 'Album')).toBe('Artist / Album');
  });

  it('drops an album or artist that only repeats the title', () => {
    expect(artistAlbumLine('Song', 'Artist', 'Song')).toBe('Artist');
    expect(artistAlbumLine('Evening', 'evening', 'Album')).toBe('Album');
  });

  it('is empty when nothing but the title is known', () => {
    expect(artistAlbumLine('Song', '', ' ')).toBe('');
  });
});

describe('joinMeta', () => {
  it('joins with a slash that stays clear next to signed values', () => {
    expect(META_SEP).toBe(' / ');
    expect(joinMeta('64%', '-28.9 dB')).toBe('64% / -28.9 dB');
  });

  it('skips empty parts', () => {
    expect(joinMeta('AirPlay', '', 'FLAC')).toBe('AirPlay / FLAC');
    expect(joinMeta(null, 'Spotify')).toBe('Spotify');
  });
});
