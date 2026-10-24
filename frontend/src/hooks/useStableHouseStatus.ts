/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * The house remote follows the held session, not only the latest poll.
 */

import type { PlayerStatus, SyncState } from '@/api/types';
import { fleetHouseStatus, type FleetHouseStatus } from '@/lib/fleetStatus';
import { LIVE_HOUSE_SESSION } from '@/lib/houseSession';
import { useFleetStore } from '@/store/fleetStore';

/** House remote follows the session, not the last poll. */
export function useStableHouseStatus(
  devices: PlayerStatus[],
  sync: SyncState | null,
): FleetHouseStatus {
  const session = useFleetStore((s) => s.houseSession) ?? LIVE_HOUSE_SESSION;
  return fleetHouseStatus(devices, sync, session);
}
