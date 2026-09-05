import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';
afterEach(cleanup);

// jsdom has no layout observer; browser tests cover actual geometry.
globalThis.ResizeObserver = class ResizeObserver { observe() {} unobserve() {} disconnect() {} };
