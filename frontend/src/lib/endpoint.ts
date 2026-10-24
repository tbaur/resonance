/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Canonical ip:port for a player, and the host and model lines the UI shows.
 */

import type { PlayerStatus } from '@/api/types';
import { META_SEP } from '@/lib/meta';

const DEFAULT_BLUOS_PORT = 11000;

/** Canonical ``ip:port`` for BluOS API / sync membership. */
export function deviceEndpoint(device: Pick<PlayerStatus, 'ip' | 'port'>): string {
  const port = device.port ?? DEFAULT_BLUOS_PORT;
  return `${device.ip}:${port}`;
}

/** Display host; include port when it is not the primary BluOS port. */
export function formatDeviceHost(device: Pick<PlayerStatus, 'ip' | 'port'>): string {
  const port = device.port ?? DEFAULT_BLUOS_PORT;
  if (port === DEFAULT_BLUOS_PORT) return device.ip;
  return `${device.ip}:${port}`;
}

/** Model line for fleet/detail; appends CI zone when present. */
export function formatDeviceHardware(
  device: Pick<PlayerStatus, 'full_model' | 'model' | 'zone'>,
): string {
  const model = device.full_model || device.model || 'BluOS';
  if (typeof device.zone === 'number' && device.zone > 0) {
    return `${model}${META_SEP}Zone ${device.zone}`;
  }
  return model;
}

export function endpointsMatch(
  a: string | undefined | null,
  b: string | undefined | null,
): boolean {
  if (!a || !b) return false;
  const norm = (value: string) => (value.includes(':') ? value : `${value}:${DEFAULT_BLUOS_PORT}`);
  return norm(a) === norm(b);
}
