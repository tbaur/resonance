/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * A render error shows a generic message and hides the thrown error.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from '@/components/ErrorBoundary';

function Boom(): never {
  throw new Error('secret internals');
}

describe('ErrorBoundary', () => {
  it('shows a generic message and does not leak the thrown error', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText('Something went wrong rendering this page.')).toBeInTheDocument();
    expect(screen.queryByText('secret internals')).not.toBeInTheDocument();
    spy.mockRestore();
  });

  it('renders the page again after Try again', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    let broken = true;
    function Flaky() {
      if (broken) throw new Error('once');
      return <p>Recovered</p>;
    }
    render(
      <ErrorBoundary>
        <Flaky />
      </ErrorBoundary>,
    );
    broken = false;
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(screen.getByText('Recovered')).toBeInTheDocument();
    spy.mockRestore();
  });
});
