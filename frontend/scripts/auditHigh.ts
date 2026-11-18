/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Which high and critical npm audit findings still fail CI.
 * picomatch has no patched release. Vite and Vitest install it
 * for their own globs, and the app never imports it.
 * The exception fails on PICOMATCH_REVIEW_BY, and sooner when
 * GitHub lists a patched release.
 */

import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

/** Unfixed picomatch ReDoS. Remove this when a patched release exists. */
export const PICOMATCH_ADVISORY = 'GHSA-fc5q-39xc-vjpf';

/**
 * CI fails on this day until someone checks the advisory.
 * Move the date only if picomatch still has no patched release.
 */
export const PICOMATCH_REVIEW_BY = '2026-12-01';

const ADVISORY_URL = `https://api.github.com/advisories/${PICOMATCH_ADVISORY}`;

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

export type PicomatchAdvisory = {
  patchedVersions: string | null;
  withdrawnAt: string | null;
};

/** UTC calendar day, so CI and a laptop agree on the review date. */
export function utcDay(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

/** True on the review day and after it. */
export function reviewIsDue(today: string, reviewBy: string = PICOMATCH_REVIEW_BY): boolean {
  return today >= reviewBy;
}

/** Read whether GitHub still lists picomatch as unfixed. */
export function parsePicomatchAdvisory(value: unknown): PicomatchAdvisory {
  if (!isRecord(value)) throw new Error('GitHub advisory was not an object');
  const withdrawnAt =
    value.withdrawn_at === null || value.withdrawn_at === undefined
      ? null
      : requireString(value.withdrawn_at, 'GitHub advisory withdrawn_at');
  const vulnerabilities = value.vulnerabilities;
  if (!Array.isArray(vulnerabilities)) {
    throw new Error('GitHub advisory vulnerabilities was not a list');
  }
  for (const item of vulnerabilities) {
    if (!isRecord(item)) throw new Error('GitHub advisory vulnerability was not an object');
    const pkg = item.package;
    if (!isRecord(pkg)) throw new Error('GitHub advisory package was not an object');
    if (pkg.ecosystem !== 'npm' || pkg.name !== 'picomatch') continue;
    const patched = item.patched_versions;
    if (patched === null || patched === undefined) return { patchedVersions: null, withdrawnAt };
    return {
      patchedVersions: requireString(patched, 'patched_versions'),
      withdrawnAt,
    };
  }
  throw new Error('GitHub advisory did not mention npm picomatch');
}

/** Messages that fail CI. Empty means the exception may stay for now. */
export function exceptionReminders(input: {
  today: string;
  advisory: PicomatchAdvisory;
  reviewBy?: string;
}): string[] {
  const reviewBy = input.reviewBy ?? PICOMATCH_REVIEW_BY;
  const messages: string[] = [];
  if (input.advisory.withdrawnAt) {
    messages.push(
      `Remove the picomatch exception. GitHub withdrew ${PICOMATCH_ADVISORY} on ${input.advisory.withdrawnAt}.`,
    );
  }
  if (input.advisory.patchedVersions) {
    messages.push(
      `Remove the picomatch exception. A patched release exists (${input.advisory.patchedVersions}).`,
    );
  }
  if (reviewIsDue(input.today, reviewBy)) {
    messages.push(
      `The picomatch exception was due for review on ${reviewBy}. Check ${PICOMATCH_ADVISORY}. If there is still no patched release, move the date in frontend/scripts/auditHigh.ts. If there is one, remove the exception.`,
    );
  }
  return messages;
}

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

async function readAdvisory(): Promise<unknown> {
  let lastError: Error | undefined;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(ADVISORY_URL, {
        headers: {
          accept: 'application/vnd.github+json',
          'user-agent': 'resonance-audit',
        },
        signal: AbortSignal.timeout(10_000),
      });
      if (!response.ok) throw new Error(`GitHub advisory lookup failed (${response.status})`);
      const value: unknown = await response.json();
      return value;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error('GitHub advisory lookup failed');
      if (attempt < 2) {
        const delay = 500 * 2 ** attempt + Math.floor(Math.random() * 200);
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }
  }
  throw new Error(`Could not check ${PICOMATCH_ADVISORY}`, { cause: lastError });
}

async function main(): Promise<void> {
  const reviewOnly = process.argv.includes('--review');
  const problems = exceptionReminders({
    today: utcDay(),
    advisory: parsePicomatchAdvisory(await readAdvisory()),
  });
  if (!reviewOnly) {
    const decision = decideAudit(parseAuditReport(readAudit()));
    if (decision.blocking.length > 0) {
      problems.push(`High audit findings:\n${decision.blocking.join('\n')}`);
    }
    if (decision.allowedMissing.length > 0) {
      problems.push(
        `Remove the allowlist entry, the advisory is gone:\n${decision.allowedMissing.join('\n')}`,
      );
    }
  }
  if (problems.length > 0) {
    console.error(problems.join('\n\n'));
    process.exit(1);
  }
  console.log(
    reviewOnly
      ? `${PICOMATCH_ADVISORY} is still unfixed. The exception is reviewed again on ${PICOMATCH_REVIEW_BY}.`
      : `High audit allows ${PICOMATCH_ADVISORY} until ${PICOMATCH_REVIEW_BY}, or sooner if a patched picomatch release exists.`,
  );
}

const entry = process.argv[1];
if (entry && import.meta.url === pathToFileURL(entry).href) {
  main().catch((error: unknown) => {
    const message = error instanceof Error ? error.message : 'Picomatch exception check failed';
    const cause =
      error instanceof Error && error.cause instanceof Error ? `: ${error.cause.message}` : '';
    console.error(`${message}${cause}`);
    process.exit(1);
  });
}
