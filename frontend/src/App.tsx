/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Routes for the fleet, the house, and one player.
 *
 * One live event stream serves the whole app.
 */

import { Navigate, Route, Routes } from 'react-router';
import { FleetPage } from '@/components/FleetPage';
import { HousePage } from '@/components/HousePage';
import { PlayerDetailPage } from '@/components/PlayerDetailPage';
import { ScrollToTop } from '@/components/ScrollToTop';
import { SessionGate } from '@/components/SessionGate';
import { useLiveFleet } from '@/hooks/useLiveFleet';

export function App() {
  return (
    <SessionGate>
      <AppRoutes />
    </SessionGate>
  );
}

function AppRoutes() {
  // One live stream for the whole SPA. Pages must not open their own.
  useLiveFleet();

  return (
    <>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<FleetPage />} />
        <Route path="/house" element={<HousePage />} />
        <Route path="/player/:id" element={<PlayerDetailPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
