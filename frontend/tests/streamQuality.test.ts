/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Each stream fact shows once, with units, in one style for every service.
 */

import { describe, expect, it } from 'vitest';
import { streamQualityLabel, type StreamInfo } from '@/lib/streamQuality';

function label(quality: string, stream_format: string, mqa_original_rate?: number): string {
  const info: StreamInfo = { quality, stream_format, mqa_original_rate };
  return streamQualityLabel(info);
}

describe('streamQualityLabel', () => {
  it('shows a lossy rate once when the format already carries it', () => {
    expect(label('256000', 'AAC 256 kb/s')).toBe('AAC 256 kbps');
  });

  it('joins the codec and a bps quality into one segment', () => {
    expect(label('320000', 'Ogg Vorbis')).toBe('Ogg Vorbis 320 kbps');
  });

  it('keeps a codec alone when no rate is sent', () => {
    expect(label('', 'AAC')).toBe('AAC');
  });

  it('keeps small numeric values as kbps', () => {
    expect(label('320', '')).toBe('320 kbps');
  });

  it('spells out lossless depth and rate and drops the tier that restates them', () => {
    expect(label('cd', 'FLAC 16/44.1')).toBe('FLAC 16-bit 44.1 kHz');
    expect(label('hd', 'FLAC 24/96')).toBe('FLAC 24-bit 96 kHz');
  });

  it('shows Roon PCM from the backend format', () => {
    expect(label('', 'PCM 24/48')).toBe('PCM 24-bit 48 kHz');
  });

  it('shows the MQA original rate and the stream it arrives in', () => {
    expect(label('mqa', 'PCM 24/48', 192000)).toBe('MQA 192 kHz (24-bit 48 kHz stream)');
  });

  it('does not repeat the rate when MQA and the stream rate match', () => {
    expect(label('mqa', 'PCM 24/44.1', 44100)).toBe('MQA 44.1 kHz (24-bit stream)');
  });

  it('keeps tiers that cannot be restated from numbers', () => {
    expect(label('cd', 'FLAC')).toBe('FLAC / CD');
    expect(label('mqa', '')).toBe('MQA');
    expect(label('mqa', 'FLAC 24/48')).toBe('FLAC 24-bit 48 kHz / MQA');
  });

  it('passes unknown format text through as is', () => {
    expect(label('', 'Some Codec v2')).toBe('Some Codec v2');
  });

  it('returns empty when nothing is available', () => {
    expect(label('', '')).toBe('');
  });
});
