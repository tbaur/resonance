/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * A pill that opens Valence. It shows only when the
 * server has Valence's address. In the Mac Dock app, a
 * plain click opens another window of this app so Safari
 * does not take over.
 */

import { useEffect, useState, type MouseEvent } from 'react';
import { api } from '@/api/client';

const WEB_ADDRESS = /^https?:\/\//i;
const VALENCE_WINDOW = 'resonance-valence';

/**
 * The Mac Dock app. An iPhone home-screen app also reports standalone,
 * and a new window there still opens Safari.
 */
function macDockApp(): boolean {
  const nav: Navigator & { standalone?: boolean } = navigator;
  if (nav.standalone === true) return false;
  if (typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(display-mode: standalone)').matches;
}

/** A pill that opens Valence. It shows only when the server has Valence's address. */
export function ValenceLink() {
  const [url, setUrl] = useState('');

  useEffect(() => {
    api
      .links()
      .then((links) => setUrl(links.valence_url))
      .catch(() => setUrl(''));
  }, []);

  function onClick(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    if (!macDockApp()) return;
    const opened = window.open(url, VALENCE_WINDOW);
    if (opened == null) return;
    event.preventDefault();
    opened.opener = null;
  }

  if (!WEB_ADDRESS.test(url)) return null;
  return (
    <a
      className="pill pill-link"
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={onClick}
    >
      Valence
    </a>
  );
}
