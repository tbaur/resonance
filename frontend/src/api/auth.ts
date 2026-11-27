/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * The request header the server requires on writes, and the signal that the
 * session cookie stopped working.
 *
 * No API token is ever compiled into the UI: anyone who can load the page
 * could read it from the bundle. The browser opens a session with the token
 * form instead, and holds only the HttpOnly session cookie.
 */

/** Sent with every API call. The server requires it on every request that changes state. */
export const REQUEST_HEADER = 'X-Resonance-Request';

type Listener = () => void;
const sessionLostListeners = new Set<Listener>();

/** Run `listener` when the server stops accepting this browser. Returns the unsubscribe. */
export function onSessionLost(listener: Listener): () => void {
  sessionLostListeners.add(listener);
  return () => {
    sessionLostListeners.delete(listener);
  };
}

/**
 * Report a 401 from the API. The server's token changed or the server
 * restarted with a new one, so the cookie no longer works.
 */
export function reportSessionLost(): void {
  for (const listener of sessionLostListeners) listener();
}
