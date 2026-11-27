/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Renders the app once this browser may call the API. Until then it
 * shows the token form or a notice.
 */

import {
  type ReactNode,
  type SyntheticEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { onSessionLost } from '@/api/auth';
import { api } from '@/api/client';
import { ApiError } from '@/api/types';

/** How often to look for the API again while it is not answering. */
const RETRY_MS = 5000;

type GateState =
  | { kind: 'checking' }
  | { kind: 'ready' }
  | { kind: 'token' }
  | { kind: 'unreachable' }
  /** The server answered and refused, for a reason a retry will not fix. */
  | { kind: 'refused'; message: string; code: string };

function isUnauthorized(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401;
}

/**
 * Ready when this browser can call the API, `token` on a 401, `refused` on
 * another 400 or 403 (such as a host name the server does not answer to), and
 * `unreachable` when the server did not answer.
 */
async function probe(): Promise<GateState> {
  try {
    await api.listDevices();
    return { kind: 'ready' };
  } catch (err) {
    if (isUnauthorized(err)) return { kind: 'token' };
    if (err instanceof ApiError && (err.status === 400 || err.status === 403)) {
      return { kind: 'refused', message: err.message, code: err.code };
    }
    return { kind: 'unreachable' };
  }
}

/** Renders `children` once the API accepts this browser; until then, the token form or a notice. */
export function SessionGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<GateState>({ kind: 'checking' });
  const [retrying, setRetrying] = useState(false);
  const inFlight = useRef(false);

  const check = useCallback(() => {
    if (inFlight.current) return;
    inFlight.current = true;
    setRetrying(true);
    void probe()
      .then(setState)
      .finally(() => {
        inFlight.current = false;
        setRetrying(false);
      });
  }, []);

  useEffect(check, [check]);

  // A 401 anywhere (the server's token changed, or it restarted with a new
  // one) means the cookie stopped working: ask for the token again.
  useEffect(
    () =>
      onSessionLost(() => {
        setState({ kind: 'token' });
      }),
    [],
  );

  useEffect(() => {
    if (state.kind !== 'unreachable') return undefined;
    const timer = window.setInterval(check, RETRY_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [state.kind, check]);

  if (state.kind === 'ready') return <>{children}</>;
  if (state.kind === 'checking') return null;
  if (state.kind === 'unreachable') return <UnreachableNotice busy={retrying} onRetry={check} />;
  if (state.kind === 'refused') {
    return (
      <RefusedNotice message={state.message} code={state.code} busy={retrying} onRetry={check} />
    );
  }
  return (
    <TokenForm
      onAccepted={() => {
        setState({ kind: 'ready' });
      }}
    />
  );
}

function GateCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="session-gate">
      <section className="panel session-card" aria-labelledby="session-title">
        <p className="session-brand">BluOS</p>
        <h1 id="session-title">{title}</h1>
        {children}
      </section>
    </main>
  );
}

function UnreachableNotice({ busy, onRetry }: { busy: boolean; onRetry: () => void }) {
  return (
    <GateCard title="Can’t reach Resonance">
      <p className="session-copy">
        The page loaded, but the Resonance server is not answering. It may be starting up or
        restarting.
      </p>
      <p className="session-hint" aria-live="polite">
        {busy ? 'Checking…' : 'Trying again every few seconds.'}
      </p>
      <button type="button" className="btn session-submit" disabled={busy} onClick={onRetry}>
        Try again now
      </button>
    </GateCard>
  );
}

function RefusedNotice({
  message,
  code,
  busy,
  onRetry,
}: {
  message: string;
  code: string;
  busy: boolean;
  onRetry: () => void;
}) {
  return (
    <GateCard title="Resonance refused this page">
      <p className="session-copy" role="alert">
        {message}
      </p>
      {code === 'host_not_allowed' ? (
        <p className="session-hint">
          Open Resonance by its IP address or <code>localhost</code>, add this name to{' '}
          <code>RESONANCE_ALLOWED_HOSTS</code> on the server, or set{' '}
          <code>RESONANCE_API_TOKEN</code>.
        </p>
      ) : null}
      <button type="button" className="btn session-submit" disabled={busy} onClick={onRetry}>
        Try again
      </button>
    </GateCard>
  );
}

function TokenForm({ onAccepted }: { onAccepted: () => void }) {
  const [token, setToken] = useState('');
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => inputRef.current?.focus(), []);

  const submit = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = token.trim();
    if (!value || busy) return;
    setBusy(true);
    setError('');
    try {
      await api.openSession(value);
      onAccepted();
    } catch (err) {
      setError(
        isUnauthorized(err)
          ? 'That token does not match the one set on the server.'
          : 'Could not reach Resonance. Check the connection and try again.',
      );
      setBusy(false);
      inputRef.current?.select();
    }
  };

  return (
    <GateCard title="Enter the API token">
      <p className="session-copy">
        This Resonance server is locked with an API token. Your players do not use it; only this
        page does.
      </p>
      <form className="session-form" onSubmit={(event) => void submit(event)}>
        <label htmlFor="api-token">API token</label>
        <div className="session-field" data-invalid={error ? 'true' : undefined}>
          <input
            ref={inputRef}
            id="api-token"
            type={visible ? 'text' : 'password'}
            autoComplete="current-password"
            autoCapitalize="off"
            spellCheck={false}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? 'api-token-error' : undefined}
            value={token}
            onChange={(event) => {
              setToken(event.target.value);
            }}
          />
          <button
            type="button"
            className="btn btn-quiet session-reveal"
            aria-controls="api-token"
            onClick={() => {
              setVisible((shown) => !shown);
            }}
          >
            {visible ? 'Hide' : 'Show'}
          </button>
        </div>
        {error ? (
          <p id="api-token-error" className="session-error" role="alert">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          className="btn btn-primary session-submit"
          disabled={!token.trim() || busy}
        >
          {busy ? 'Checking…' : 'Continue'}
        </button>
      </form>
      <p className="session-hint">
        It is the <code>RESONANCE_API_TOKEN</code> value on the server. This browser stays signed in
        until it closes.
      </p>
    </GateCard>
  );
}
