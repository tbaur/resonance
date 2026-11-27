/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Shape checks for JSON from the server, so a payload that is not what the
 * views expect is refused at the edge instead of breaking a render.
 */

import type {
  AppLinks,
  AudioInput,
  BluetoothResponse,
  DeviceSetting,
  DeviceSettingsResponse,
  DevicesResponse,
  DiagnoseResponse,
  FleetActionResponse,
  FleetFirmwareResponse,
  FleetHealthResponse,
  FleetUpgradeResponse,
  FleetVolumeResponse,
  PlayerStatus,
  Preset,
  QueueResponse,
  SyncEnableResponse,
  SyncState,
  UpgradeStatus,
  VersionInfo,
} from './types';

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

function hasStrings(value: Record<string, unknown>, ...keys: string[]): boolean {
  return keys.every((key) => typeof value[key] === 'string');
}

function hasNumbers(value: Record<string, unknown>, ...keys: string[]): boolean {
  return keys.every((key) => typeof value[key] === 'number');
}

function arrayOf<T>(item: (value: unknown) => value is T) {
  return (body: unknown): body is T[] => Array.isArray(body) && body.every(item);
}

export function isAppLinks(body: unknown): body is AppLinks {
  return isRecord(body) && hasStrings(body, 'valence_url');
}

export function isVersionInfo(body: unknown): body is VersionInfo {
  return isRecord(body) && hasStrings(body, 'version');
}

export function isDiagnose(body: unknown): body is DiagnoseResponse {
  return isRecord(body) && hasStrings(body, 'device_id', 'ip', 'name');
}

function isDeviceSetting(value: unknown): value is DeviceSetting {
  return (
    isRecord(value) &&
    hasStrings(value, 'id', 'kind', 'value', 'display_name') &&
    Array.isArray(value.options)
  );
}

export function isDeviceSettings(body: unknown): body is DeviceSettingsResponse {
  return (
    isRecord(body) &&
    hasStrings(body, 'page_id') &&
    Array.isArray(body.settings) &&
    body.settings.every(isDeviceSetting)
  );
}

export function isUpgradeStatus(body: unknown): body is UpgradeStatus {
  return (
    isRecord(body) &&
    hasStrings(body, 'device_id', 'message') &&
    typeof body.update_available === 'boolean' &&
    typeof body.ok === 'boolean'
  );
}

export function isFleetFirmware(body: unknown): body is FleetFirmwareResponse {
  return isRecord(body) && Array.isArray(body.unique_versions) && Array.isArray(body.devices);
}

export function isFleetUpgrades(body: unknown): body is FleetUpgradeResponse {
  return (
    isRecord(body) &&
    hasNumbers(body, 'updates_available', 'checked', 'failed') &&
    Array.isArray(body.results) &&
    body.results.every(isUpgradeStatus)
  );
}

export function isFleetAction(body: unknown): body is FleetActionResponse {
  return isRecord(body) && hasNumbers(body, 'succeeded', 'failed') && Array.isArray(body.results);
}

export function isFleetVolume(body: unknown): body is FleetVolumeResponse {
  return (
    isRecord(body) &&
    hasNumbers(body, 'level', 'succeeded', 'failed') &&
    Array.isArray(body.results)
  );
}

export function isSyncEnable(body: unknown): body is SyncEnableResponse {
  return (
    isRecord(body) &&
    hasStrings(body, 'primary_id') &&
    hasNumbers(body, 'succeeded', 'failed') &&
    Array.isArray(body.results)
  );
}

export function isQueue(body: unknown): body is QueueResponse {
  return (
    isRecord(body) &&
    hasNumbers(body, 'count') &&
    Array.isArray(body.items) &&
    body.items.every((item) => isRecord(item) && hasStrings(item, 'title'))
  );
}

export const isAudioInputs = arrayOf(
  (value: unknown): value is AudioInput =>
    isRecord(value) && hasStrings(value, 'name', 'id') && typeof value.selected === 'boolean',
);

export function isBluetooth(body: unknown): body is BluetoothResponse {
  return isRecord(body) && typeof body.supported === 'boolean';
}

export const isPresets = arrayOf(
  (value: unknown): value is Preset => isRecord(value) && hasStrings(value, 'id', 'name'),
);
