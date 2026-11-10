// 测试脚手架：统一 jest-dom 匹配器、重置外部状态。
import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import { resetCoordCache, resetCoordComputeCount } from '../src/coord/gcj02bd09';

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  resetCoordCache();
  resetCoordComputeCount();
  vi.unstubAllGlobals();
});
