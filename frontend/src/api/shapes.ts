/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Shape checks for JSON from the server, so a payload that is not what the
 * views expect is refused at the edge instead of breaking a render.
 */

import type { DevicesResponse, FleetHealthResponse, PlayerStatus, SyncState } from './types';

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The fields every view reads without a fallback. */
export function isPlayerStatus(value: unknown): value is PlayerStatus {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    typeof value.ip === 'string' &&
    typeof value.name === 'string' &&
    typeof value.volume === 'number' &&
    typeof value.state === 'string'
  );
}

export function isDevicesResponse(body: unknown): body is DevicesResponse {
  return isRecord(body) && Array.isArray(body.devices) && body.devices.every(isPlayerStatus);
}

export function isSyncState(body: unknown): body is SyncState {
  return isRecord(body) && Array.isArray(body.groups) && Array.isArray(body.standalone_ids);
}

export function isFleetHealth(body: unknown): body is FleetHealthResponse {
  return isRecord(body) && Array.isArray(body.drops) && isRecord(body.first_online);
}
