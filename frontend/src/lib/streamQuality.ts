/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * BluOS stream format for the UI. Each fact shows once, with units: the codec
 * and its rate share one segment ("AAC 256 kbps", "FLAC 16-bit 44.1 kHz").
 */

import type { PlayerStatus } from '@/api/types';
import { joinMeta } from '@/lib/meta';

export type StreamInfo = Pick<PlayerStatus, 'quality' | 'stream_format' | 'mqa_original_rate'>;

type ParsedFormat = {
  codec: string;
  kbps: number | null;
  bits: number | null;
  khz: string | null;
};

// "AAC 256 kb/s" (Apple Music).
const LOSSY_FORMAT = /^(.+?)\s+(\d+)\s*(?:kb\/s|kbps|kbit\/s)$/i;
// "FLAC 16/44.1" (TIDAL) and "PCM 24/48" (Roon, built by the backend).
const LOSSLESS_FORMAT = /^(.+?)\s+(\d{1,2})\s*\/\s*(\d{1,3}(?:\.\d+)?)$/;
// Tiers that only restate a bit depth and sample rate.
const RATE_TIERS = new Set(['cd', 'hd']);

function khzLabel(value: number): string {
  return String(Number(value.toFixed(1)));
}

function parseFormat(raw: string): ParsedFormat {
  const lossy = LOSSY_FORMAT.exec(raw);
  if (lossy) return { codec: lossy[1], kbps: Number(lossy[2]), bits: null, khz: null };
  const lossless = LOSSLESS_FORMAT.exec(raw);
  if (lossless) {
    return {
      codec: lossless[1],
      kbps: null,
      bits: Number(lossless[2]),
      khz: khzLabel(Number(lossless[3])),
    };
  }
  return { codec: raw, kbps: null, bits: null, khz: null };
}

/** BluOS sends lossy rates as bits/sec (256000) and sometimes as plain kbps (256). */
function kbpsFromQuality(raw: string): number | null {
  if (!/^\d+$/.test(raw)) return null;
  const n = Number(raw);
  if (n <= 0) return null;
  return n >= 1000 ? Math.round(n / 1000) : n;
}

function codecSegment(format: ParsedFormat, kbps: number | null): string {
  if (kbps !== null) return format.codec ? `${format.codec} ${kbps} kbps` : `${kbps} kbps`;
  if (format.bits !== null && format.khz !== null) {
    return `${format.codec} ${format.bits}-bit ${format.khz} kHz`;
  }
  return format.codec;
}

/** "MQA 192 kHz (24-bit 48 kHz stream)", or "MQA 44.1 kHz (24-bit stream)" when the rates match. */
function mqaSegment(format: ParsedFormat, originalHz: number): string | null {
  if (originalHz <= 0 || format.bits === null || format.khz === null) return null;
  const original = khzLabel(originalHz / 1000);
  const stream = original === format.khz ? `${format.bits}-bit` : `${format.bits}-bit ${format.khz} kHz`;
  return `MQA ${original} kHz (${stream} stream)`;
}

function tierLabel(tier: string, format: ParsedFormat): string | null {
  const lower = tier.toLowerCase();
  if (RATE_TIERS.has(lower) && format.bits !== null && format.khz !== null) return null;
  if (format.codec.toLowerCase().includes(lower)) return null;
  return tier.toUpperCase();
}

/** Format BluOS quality, streamFormat, and the MQA original rate as one meta segment group. */
export function streamQualityLabel(info: StreamInfo): string {
  const format = parseFormat(info.stream_format?.trim() ?? '');
  const quality = info.quality?.trim() ?? '';
  const qualityKbps = kbpsFromQuality(quality);

  if (quality.toLowerCase().startsWith('mqa')) {
    const mqa = mqaSegment(format, info.mqa_original_rate ?? 0);
    if (mqa) return mqa;
  }
  const codec = codecSegment(format, qualityKbps ?? format.kbps);
  const tier = quality && !/^\d+$/.test(quality) ? tierLabel(quality, format) : null;
  return joinMeta(codec, tier);
}
