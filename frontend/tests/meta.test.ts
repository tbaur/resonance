/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Meta parts join with a slash.
 */

import { describe, expect, it } from 'vitest';
import { META_SEP, artistAlbumLines, joinMeta } from '@/lib/meta';

describe('artistAlbumLines', () => {
  it('keeps artist and album as separate lines', () => {
    expect(artistAlbumLines('Song', 'Artist', 'Album')).toEqual({ artist: 'Artist', album: 'Album' });
  });

  it('drops an album or artist that only repeats the title', () => {
    expect(artistAlbumLines('Song', 'Artist', 'Song')).toEqual({ artist: 'Artist', album: '' });
    expect(artistAlbumLines('Evening', 'evening', 'Album')).toEqual({ artist: '', album: 'Album' });
  });

  it('shows a self-titled album once', () => {
    expect(artistAlbumLines('Song', 'Band', 'Band')).toEqual({ artist: 'Band', album: '' });
  });

  it('is empty when nothing but the title is known', () => {
    expect(artistAlbumLines('Song', '', ' ')).toEqual({ artist: '', album: '' });
  });
});

describe('joinMeta', () => {
  it('joins with a pipe that stays clear next to signed values', () => {
    expect(META_SEP).toBe(' | ');
    expect(joinMeta('64%', '-28.9 dB')).toBe('64% | -28.9 dB');
  });

  it('skips empty parts', () => {
    expect(joinMeta('AirPlay', '', 'FLAC')).toBe('AirPlay | FLAC');
    expect(joinMeta(null, 'Spotify')).toBe('Spotify');
  });
});
