/** Optional API token mirrored from Vite env (pair with backend RESONANCE_API_TOKEN). */
export const apiToken = (import.meta.env.VITE_API_TOKEN as string | undefined)?.trim() || '';

/** Sent with every API call. The server requires it on cookie-authenticated writes. */
export const REQUEST_HEADER = 'X-Resonance-Request';
