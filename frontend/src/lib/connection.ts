/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Labels for the realtime connection to the Resonance server.
 */

import type { ConnectionState } from '@/store/fleetStore';

const CONNECTION_LABEL: Record<ConnectionState, string> = {
  live: 'Live updates',
  connecting: 'Connecting…',
  reconnecting: 'Reconnecting…',
  offline: 'Offline',
};

export function connectionLabel(state: ConnectionState): string {
  return CONNECTION_LABEL[state];
}
