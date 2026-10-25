/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Connection, player count, and how the fleet was discovered.
 */

import { connectionLabel } from '@/lib/connection';
import { discoveryLabel, playerCountLabel } from '@/lib/discovery';
import type { ConnectionState } from '@/store/fleetStore';

interface StatusPillsProps {
  connection: ConnectionState;
  deviceCount: number;
  discoveryMethod: string;
  loading: boolean;
}

export function StatusPills({
  connection,
  deviceCount,
  discoveryMethod,
  loading,
}: StatusPillsProps) {
  const discovery = discoveryLabel(discoveryMethod);
  const playersLabel = loading ? 'Scanning…' : playerCountLabel(deviceCount);

  return (
    <div className="status-pills" role="status" aria-live="polite">
      <span
        className="pill pill-connection"
        data-state={connection}
        title="Realtime connection to the Resonance server"
      >
        <span className="pill-dot" aria-hidden="true" />
        <span className="pill-label">{connectionLabel(connection)}</span>
      </span>
      <span
        className="pill pill-fleet"
        title={
          discovery
            ? `Network discovery via ${discovery}`
            : 'Players currently on the LAN'
        }
      >
        {playersLabel}
        {discovery && !loading ? (
          <span className="pill-muted"> / via {discovery}</span>
        ) : null}
      </span>
    </div>
  );
}
