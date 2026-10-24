/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * The API token compiled into the UI.
 *
 * Cookie-authenticated writes must also send X-Resonance-Request.
 */

/** Optional API token mirrored from Vite env (pair with backend RESONANCE_API_TOKEN). */
export const apiToken = (import.meta.env.VITE_API_TOKEN as string | undefined)?.trim() || '';

/** Sent with every API call. The server requires it on cookie-authenticated writes. */
export const REQUEST_HEADER = 'X-Resonance-Request';
