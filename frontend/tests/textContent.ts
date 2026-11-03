/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Text matcher for lines split across elements, such as meta lines with dimmed separators.
 */

import type { MatcherFunction } from '@testing-library/react';

/** Matches the innermost element whose full text content matches `expected`. */
export function byTextContent(expected: string | RegExp): MatcherFunction {
  const matches = (text: string | null | undefined): boolean =>
    text != null && (typeof expected === 'string' ? text === expected : expected.test(text));
  return (_content, element) => {
    if (!element || !matches(element.textContent)) return false;
    return !Array.from(element.children).some((child) => matches(child.textContent));
  };
}
