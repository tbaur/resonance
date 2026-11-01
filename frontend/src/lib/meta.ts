/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Separator for compact meta lines: volume, dB, service, format, status.
 *
 * A slash stays legible beside a signed value such as -28.9 dB. A middot does not.
 */

export const META_SEP = ' / ';

export function joinMeta(
  ...parts: Array<string | number | null | undefined | false>
): string {
  return parts.filter((part): part is string | number => Boolean(part)).join(META_SEP);
}

function sameName(left: string, right: string): boolean {
  return left.trim().localeCompare(right.trim(), undefined, { sensitivity: 'accent' }) === 0;
}

/** Artist / album under a title; drops any part that only repeats a name already shown. */
export function artistAlbumLine(title: string, artist: string, album: string): string {
  const shownArtist = !sameName(artist, title) && artist.trim();
  const shownAlbum = !sameName(album, title) && !sameName(album, artist) && album.trim();
  return joinMeta(shownArtist, shownAlbum);
}