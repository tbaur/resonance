/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Moving the first queue track down, and ignoring an index outside the queue.
 */

import { describe, expect, it } from 'vitest';
import type { QueueResponse } from '@/api/types';
import { reorderQueue } from '@/lib/queue';

const queue: QueueResponse = {
  count: 3,
  items: [
    { title: 'A', artist: '1', album: '', image: '', service: '' },
    { title: 'B', artist: '2', album: '', image: '', service: '' },
    { title: 'C', artist: '3', album: '', image: '', service: '' },
  ],
};

describe('reorderQueue', () => {
  it('moves the first track down', () => {
    expect(reorderQueue(queue, 0, 1).items.map((item) => item.title)).toEqual(['B', 'A', 'C']);
  });

  it('ignores out-of-range indexes', () => {
    expect(reorderQueue(queue, 0, 9)).toBe(queue);
  });
});
