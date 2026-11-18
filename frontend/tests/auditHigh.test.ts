/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * The high audit allows the unfixed picomatch advisory and
 * fails on any other high finding, or once that advisory is gone.
 */

import { describe, expect, it } from 'vitest';
import { decideAudit, parseAuditReport } from '../scripts/auditHigh';

const PICOMATCH_URL = 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf';

function report(vulnerabilities: unknown): ReturnType<typeof decideAudit> {
  return decideAudit(parseAuditReport({ vulnerabilities }));
}

describe('decideAudit', () => {
  it('allows the picomatch advisory through the packages that install it', () => {
    const decision = report({
      picomatch: { severity: 'high', via: [{ url: PICOMATCH_URL }] },
      fdir: { severity: 'high', via: ['picomatch'] },
      tinyglobby: { severity: 'high', via: ['fdir', 'picomatch'] },
      vite: { severity: 'high', via: ['picomatch', 'tinyglobby'] },
      '@vitest/coverage-v8': { severity: 'high', via: ['vitest'] },
      vitest: { severity: 'high', via: ['@vitest/coverage-v8', 'picomatch', 'vite'] },
    });
    expect(decision.blocking).toEqual([]);
    expect(decision.allowedPresent).toEqual(['GHSA-fc5q-39xc-vjpf']);
    expect(decision.allowedMissing).toEqual([]);
  });

  it('fails on any other high advisory', () => {
    const decision = report({
      picomatch: { severity: 'high', via: [{ url: PICOMATCH_URL }] },
      leftpad: {
        severity: 'high',
        via: [{ url: 'https://github.com/advisories/GHSA-aaaa-bbbb-cccc' }],
      },
    });
    expect(decision.blocking).toEqual(['GHSA-aaaa-bbbb-cccc']);
  });

  it('fails when the allowed advisory is gone', () => {
    const decision = report({});
    expect(decision.blocking).toEqual([]);
    expect(decision.allowedMissing).toEqual(['GHSA-fc5q-39xc-vjpf']);
  });

  it('ignores a moderate finding that is not the allowed advisory', () => {
    const decision = report({
      picomatch: { severity: 'high', via: [{ url: PICOMATCH_URL }] },
      other: {
        severity: 'moderate',
        via: [{ url: 'https://github.com/advisories/GHSA-mmmm-nnnn-oooo' }],
      },
    });
    expect(decision.blocking).toEqual([]);
  });

  it('rejects a report that is not an object', () => {
    expect(() => parseAuditReport(null)).toThrow(/not return an object/);
  });
});
