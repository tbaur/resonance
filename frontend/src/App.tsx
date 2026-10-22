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
