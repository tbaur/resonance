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

const TITLE_SEP = ' — ';

/** Track — artist, but never "Evening — Evening" when BluOS repeats the name. */
export function formatTrackArtist(track: string, artist: string): string {
  const title = track.trim();
  const name = artist.trim();
  if (!title) return name;
  if (!name) return title;
  if (title.localeCompare(name, undefined, { sensitivity: 'accent' }) === 0) {
    return title;
  }
  return `${title}${TITLE_SEP}${name}`;
}
