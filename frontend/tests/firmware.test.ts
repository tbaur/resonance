/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Dotted firmware versions sort in numeric order.
 */

import { describe, expect, it } from 'vitest';
import { compareFirmware } from '@/lib/firmware';

describe('compareFirmware', () => {
  it('orders dotted versions', () => {
    expect(compareFirmware('4.10.0', '4.16.6')).toBeLessThan(0);
    expect(compareFirmware('4.16.6', '4.16.6')).toBe(0);
    expect(compareFirmware('4.16.6', '4.10.0')).toBeGreaterThan(0);
  });
});
