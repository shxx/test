import { describe, expect, it } from 'vitest';
import {
  coordComputeCount,
  coordKey,
  gcj02ToBd09,
  resetCoordCache,
  toBd09Cached,
} from '../src/coord/gcj02bd09';

describe('gcj02ToBd09', () => {
  it('converts a known point with the standard offset', () => {
    // 北京某 GCJ-02 点：BD-09 应有约 +0.006 的偏移量级。
    const bd = gcj02ToBd09(116.404, 39.915);
    expect(Math.abs(bd.lng - 116.404)).toBeLessThan(0.01);
    expect(Math.abs(bd.lat - 39.915)).toBeLessThan(0.01);
  });

  it('is deterministic', () => {
    const a = gcj02ToBd09(121.47, 31.23);
    const b = gcj02ToBd09(121.47, 31.23);
    expect(a).toEqual(b);
  });
});

describe('toBd09Cached / coord cache', () => {
  it('computes once per key and counts actual conversions', () => {
    const before = coordComputeCount();
    const key = coordKey('S1', '2026YTD08', 121.47, 31.23);
    const a = toBd09Cached(key, 121.47, 31.23);
    const b = toBd09Cached(key, 121.47, 31.23);
    expect(a).toEqual(b);
    expect(coordComputeCount()).toBe(before + 1);
  });

  it('treats different data_version as distinct keys', () => {
    const before = coordComputeCount();
    const k1 = coordKey('S1', '2026YTD08', 121.47, 31.23);
    const k2 = coordKey('S1', '2026YTD09', 121.47, 31.23);
    toBd09Cached(k1, 121.47, 31.23);
    toBd09Cached(k2, 121.47, 31.23);
    expect(coordComputeCount()).toBe(before + 2);
  });

  it('resetCoordCache forces recomputation', () => {
    const key = coordKey('S1', '2026YTD08', 121.47, 31.23);
    toBd09Cached(key, 121.47, 31.23);
    const before = coordComputeCount();
    resetCoordCache();
    toBd09Cached(key, 121.47, 31.23);
    expect(coordComputeCount()).toBe(before + 1);
  });
});
