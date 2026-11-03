/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Renders a compact meta line with its separators dimmed, so the values stand out.
 */

import { Fragment } from 'react';
import { META_SEP } from '@/lib/meta';

const SEP_MARK = META_SEP.trim();

/**
 * One dimmed separator, for lines assembled inline in JSX. The spaces stay outside the
 * span because accessible-name computation drops whitespace at element edges.
 */
export function MetaSep() {
  return (
    <>
      {' '}
      <span className="meta-sep">{SEP_MARK}</span>{' '}
    </>
  );
}

/** A string built with `META_SEP`, rendered with every separator dimmed. */
export function MetaText({ text }: { text: string }) {
  const parts = text.split(META_SEP);
  return (
    <>
      {parts.map((part, index) => (
        // Parts can repeat, so position is the only stable key.
        <Fragment key={index}>
          {index > 0 ? <MetaSep /> : null}
          {part}
        </Fragment>
      ))}
    </>
  );
}
