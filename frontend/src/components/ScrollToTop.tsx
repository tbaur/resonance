/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Resets window scroll when the route changes.
 */

import { useEffect } from 'react';
import { useLocation } from 'react-router';

/** Reset window scroll on route changes (SPA pages don't do this by default). */
export function ScrollToTop() {
  const { pathname } = useLocation();

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return null;
}
