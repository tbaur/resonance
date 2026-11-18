/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Which high and critical npm audit findings still fail CI.
 * picomatch has no patched release. Vite and Vitest install it
 * for their own globs, and the app never imports it.
 */

import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

/** Unfixed picomatch ReDoS. Remove this when the advisory leaves the audit. */
export const PICOMATCH_ADVISORY = 'GHSA-fc5q-39xc-vjpf';

const BLOCKING_SEVERITIES = new Set(['high', 'critical']);
const GHSA_PATTERN = /GHSA-[0-9a-z-]+/i;

type AuditViaObject = {
  url?: string;
  title?: string;
  name?: string;
};

type AuditVulnerability = {
  severity?: string;
  via: Array<string | AuditViaObject>;
};

export type AuditReport = {
  vulnerabilities: Record<string, AuditVulnerability>;
};

export type AuditDecision = {
  blocking: string[];
  allowedPresent: string[];
  allowedMissing: string[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requireString(value: unknown, label: string): string {
  if (typeof value !== 'string') throw new Error(`${label} was not a string`);
  return value;
}

function parseVia(value: unknown, name: string): Array<string | AuditViaObject> {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new Error(`npm audit via for ${name} was not a list`);
  return value.map((item, index) => {
    if (typeof item === 'string') return item;
    if (!isRecord(item)) {
      throw new Error(`npm audit via for ${name} item ${index} was not an object`);
    }
    const via: AuditViaObject = {};
    if (item.url !== undefined) via.url = requireString(item.url, `npm audit url for ${name}`);
    if (item.title !== undefined)
      via.title = requireString(item.title, `npm audit title for ${name}`);
    if (item.name !== undefined) via.name = requireString(item.name, `npm audit name for ${name}`);
    return via;
  });
}

/** Narrow the `npm audit --json` document before the allowlist runs. */
export function parseAuditReport(value: unknown): AuditReport {
  if (!isRecord(value)) throw new Error('npm audit did not return an object');
  const raw = value.vulnerabilities;
  if (raw === undefined) return { vulnerabilities: {} };
  if (!isRecord(raw)) throw new Error('npm audit vulnerabilities was not an object');
  const vulnerabilities: Record<string, AuditVulnerability> = {};
  for (const [name, entry] of Object.entries(raw)) {
    if (!isRecord(entry)) throw new Error(`npm audit entry for ${name} was not an object`);
    const vulnerability: AuditVulnerability = { via: parseVia(entry.via, name) };
    if (entry.severity !== undefined) {
      vulnerability.severity = requireString(entry.severity, `npm audit severity for ${name}`);
    }
    vulnerabilities[name] = vulnerability;
  }
  return { vulnerabilities };
}

function advisoryId(via: AuditViaObject): string {
  const match = GHSA_PATTERN.exec(via.url ?? '');
  if (match?.[0]) return match[0];
  return via.url || via.title || via.name || 'unknown advisory';
}

function reachableIds(
  vulnerabilities: Record<string, AuditVulnerability>,
  name: string,
  seen: Set<string>,
): Set<string> {
  const ids = new Set<string>();
  if (seen.has(name)) return ids;
  seen.add(name);
  const vulnerability = vulnerabilities[name];
  if (!vulnerability) {
    ids.add(name);
    return ids;
  }
  if (vulnerability.via.length === 0) {
    ids.add(`${name} (no advisory)`);
    return ids;
  }
  for (const via of vulnerability.via) {
    if (typeof via === 'string') {
      for (const id of reachableIds(vulnerabilities, via, seen)) ids.add(id);
      continue;
    }
    ids.add(advisoryId(via));
  }
  return ids;
}

/**
 * High and critical findings fail unless every advisory they reach is allowed.
 * An allowed id that is no longer present fails too, so the exception is removed
 * once picomatch publishes a fix.
 */
export function decideAudit(
  report: AuditReport,
  allowed: readonly string[] = [PICOMATCH_ADVISORY],
): AuditDecision {
  const present = new Set<string>();
  const blocking = new Set<string>();
  for (const [name, vulnerability] of Object.entries(report.vulnerabilities)) {
    if (!BLOCKING_SEVERITIES.has(vulnerability.severity ?? '')) continue;
    for (const id of reachableIds(report.vulnerabilities, name, new Set())) {
      present.add(id);
      if (!allowed.includes(id)) blocking.add(id);
    }
  }
  return {
    blocking: [...blocking].sort(),
    allowedPresent: allowed.filter((id) => present.has(id)),
    allowedMissing: allowed.filter((id) => !present.has(id)),
  };
}

function isAuditExit(
  error: unknown,
): error is Error & { status: number; stdout: string; stderr: string } {
  return (
    error instanceof Error &&
    'status' in error &&
    typeof error.status === 'number' &&
    'stdout' in error &&
    typeof error.stdout === 'string' &&
    'stderr' in error &&
    typeof error.stderr === 'string'
  );
}

function readAudit(): unknown {
  try {
    const stdout = execFileSync('npm', ['audit', '--json', '--audit-level=high'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const value: unknown = JSON.parse(stdout);
    return value;
  } catch (error) {
    if (!isAuditExit(error)) throw error;
    if (error.status === 1 && error.stdout) {
      const value: unknown = JSON.parse(error.stdout);
      return value;
    }
    const detail = error.stderr.trim() || error.message;
    throw new Error(`npm audit failed (${error.status}): ${detail}`, { cause: error });
  }
}

function main(): void {
  const decision = decideAudit(parseAuditReport(readAudit()));
  if (decision.blocking.length > 0 || decision.allowedMissing.length > 0) {
    if (decision.blocking.length > 0) {
      console.error(`High audit findings:\n${decision.blocking.join('\n')}`);
    }
    if (decision.allowedMissing.length > 0) {
      console.error(
        `Remove the allowlist entry, the advisory is gone:\n${decision.allowedMissing.join('\n')}`,
      );
    }
    process.exit(1);
  }
  console.log(
    `High audit allows ${decision.allowedPresent.join(', ') || PICOMATCH_ADVISORY} until picomatch publishes a patched release.`,
  );
}

const entry = process.argv[1];
if (entry && import.meta.url === pathToFileURL(entry).href) main();
