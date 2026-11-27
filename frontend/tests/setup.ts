/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * jsdom stand-ins for scroll, dialog, and pointer capture, which the
 * test browser does not implement.
 */

import '@testing-library/jest-dom/vitest';

// jsdom has no layout engine; without this, route changes print "Not implemented".
Object.defineProperty(window, 'scrollTo', {
  value: () => undefined,
  writable: true,
});

// jsdom does not implement the dialog top layer.
if (!('showModal' in HTMLDialogElement.prototype)) {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    value: function showModal(this: HTMLDialogElement) {
      this.open = true;
    },
    writable: true,
  });
}
if (!('close' in HTMLDialogElement.prototype)) {
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {
    value: function close(this: HTMLDialogElement) {
      this.open = false;
      this.dispatchEvent(new Event('close'));
    },
    writable: true,
  });
}

// jsdom has no pointer capture; the press-and-hold buttons call it on press.
if (!('setPointerCapture' in Element.prototype)) {
  Object.defineProperty(Element.prototype, 'setPointerCapture', {
    value: () => undefined,
    writable: true,
  });
}
