/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Which transport buttons apply. A live radio stream has no queue, and skips or
 * goes back only when its station offers it.
 */

import type { PlayerStatus } from '@/api/types';

export const NO_SKIP = "This station doesn't offer skip";
export const NO_BACK = "This station doesn't offer back";
export const NO_QUEUE = 'A live station has no queue to shuffle or repeat';

type Actions = Pick<PlayerStatus, 'live' | 'can_skip' | 'can_back'> | undefined;

export function canSkip(device: Actions): boolean {
  return device?.can_skip !== false;
}

export function canBack(device: Actions): boolean {
  return device?.can_back !== false;
}

export function hasQueue(device: Actions): boolean {
  return device?.live !== true;
}
