/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Only a live station turns a transport button off. Missing fields keep it on.
 */

import { describe, expect, it } from 'vitest';
import { canBack, canSkip, hasQueue } from '@/lib/stationActions';

describe('stationActions', () => {
  it('keeps every button when the fields are missing', () => {
    expect(canSkip({})).toBe(true);
    expect(canBack({})).toBe(true);
    expect(hasQueue({})).toBe(true);
    expect(canSkip(undefined)).toBe(true);
  });

  it('follows what a live station offers', () => {
    const station = { live: true, can_skip: true, can_back: false };
    expect(canSkip(station)).toBe(true);
    expect(canBack(station)).toBe(false);
    expect(hasQueue(station)).toBe(false);
  });
});
