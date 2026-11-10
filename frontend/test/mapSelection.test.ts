import { describe, expect, it } from 'vitest';
import {
  addIds,
  clearIds,
  drillTarget,
  hitTestBbox,
  normalizeBbox,
  parseBoundaryPoints,
  regionBoundaryNames,
  regionLevel,
  stepBackLevel,
  toggleId,
} from '../src/state/mapSelection';

describe('多选切换 toggleId / addIds / clearIds', () => {
  it('toggleId 未选中则加入，已选中则移除', () => {
    const s0 = new Set<string>();
    const s1 = toggleId(s0, 'S1');
    expect(s1).toEqual(new Set(['S1']));
    const s2 = toggleId(s1, 'S1');
    expect(s2).toEqual(new Set());
  });

  it('toggleId 不改变原集合（不可变）', () => {
    const s0 = new Set(['S1']);
    toggleId(s0, 'S2');
    expect(s0).toEqual(new Set(['S1']));
  });

  it('addIds 累加并入，clearIds 清空', () => {
    const s = addIds(new Set(['S1']), ['S2', 'S3']);
    expect(s).toEqual(new Set(['S1', 'S2', 'S3']));
    expect(clearIds()).toEqual(new Set());
  });
});

describe('框选命中 hitTestBbox', () => {
  const points = [
    { id: 'A', lng: 120, lat: 30 },
    { id: 'B', lng: 121, lat: 31 },
    { id: 'C', lng: 122, lat: 32 },
    { id: 'D', lng: 119, lat: 29 },
  ];

  it('返回落在包围盒内（含边界）的点', () => {
    const hit = hitTestBbox(points, { minLng: 120, minLat: 30, maxLng: 121.5, maxLat: 31.5 });
    expect(hit).toEqual(['A', 'B']);
  });

  it('normalizeBbox 规范化任意对角两点', () => {
    const bbox = normalizeBbox({ lng: 122, lat: 32 }, { lng: 120, lat: 30 });
    expect(bbox).toEqual({ minLng: 120, minLat: 30, maxLng: 122, maxLat: 32 });
  });

  it('空包围盒命中为空', () => {
    expect(hitTestBbox(points, { minLng: 130, minLat: 40, maxLng: 140, maxLat: 50 })).toEqual([]);
  });
});

describe('层级 regionLevel / drillTarget / stepBackLevel', () => {
  it('regionLevel 由 province/city 判定', () => {
    expect(regionLevel(null, null)).toBe('country');
    expect(regionLevel('上海', null)).toBe('province');
    expect(regionLevel('上海', '上海01市')).toBe('city');
  });

  it('drillTarget 市为最细层不再下钻', () => {
    expect(drillTarget('country')).toBe('province');
    expect(drillTarget('province')).toBe('city');
    expect(drillTarget('city')).toBeNull();
  });

  it('stepBackLevel 逐级回退', () => {
    expect(stepBackLevel('city')).toBe('province');
    expect(stepBackLevel('province')).toBe('country');
    expect(stepBackLevel('country')).toBe('country');
  });
});

describe('边界名称 regionBoundaryNames', () => {
  it('全国层渲染省界，省/市层渲染城市边界', () => {
    expect(regionBoundaryNames('country', ['上海', '江苏'], ['上海01市'])).toEqual(['上海', '江苏']);
    expect(regionBoundaryNames('province', ['上海', '江苏'], ['上海01市', '江苏01市'])).toEqual(['上海01市', '江苏01市']);
    expect(regionBoundaryNames('city', ['上海'], ['上海01市'])).toEqual(['上海01市']);
  });
});

describe('parseBoundaryPoints 解析百度 Boundary 坐标串', () => {
  it('解析合法坐标串', () => {
    expect(parseBoundaryPoints('116.404,39.915;116.405,39.916')).toEqual([
      { lng: 116.404, lat: 39.915 },
      { lng: 116.405, lat: 39.916 },
    ]);
  });

  it('过滤非法坐标', () => {
    expect(parseBoundaryPoints('116.404,39.915;x,y;')).toEqual([{ lng: 116.404, lat: 39.915 }]);
  });

  it('空串返回空数组', () => {
    expect(parseBoundaryPoints('')).toEqual([]);
  });
});
