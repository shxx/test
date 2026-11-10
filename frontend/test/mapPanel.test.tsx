import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { MapPanel } from '../src/ui/MapPanel';
import { FilterProvider } from '../src/state/FilterContext';
import { domainMeta, jsonRes, kpiResult, storeItem, storesResult } from './fixtures';

function envelope(data: unknown) {
  return { data, meta: { data_version: '2026YTD08', as_of_date: '2026-08-31' }, error: null, trace_id: 't1' };
}

// 最小 BMapGL 假实现：仅记录 overlay 与事件，不做真实渲染（验证交互接线，非 SDK 真机）。
class FakePoint {
  constructor(public lng: number, public lat: number) {}
}
class FakeMarker {
  handlers: Record<string, () => void> = {};
  constructor(public pt: FakePoint) {}
  addEventListener(type: string, cb: () => void) {
    this.handlers[type] = cb;
  }
}
class FakeBoundary {
  get(_name: string, cb: (rs: { boundaries?: string[] }) => void) {
    cb({ boundaries: [] });
  }
}
class FakePolygon {
  handlers: Record<string, () => void> = {};
  constructor(public pts: FakePoint[], _opts: unknown) {}
  addEventListener(type: string, cb: () => void) {
    this.handlers[type] = cb;
  }
}

let mapInstance: any;

class FakeMap {
  overlays: any[] = [];
  setViewportCalls: any[][] = [];
  constructor(_container: unknown, _opts: unknown) {
    mapInstance = this;
  }
  setViewport(v: any[]) {
    this.setViewportCalls.push(v);
  }
  centerAndZoom() {}
  clearOverlays() {
    this.overlays = [];
  }
  addOverlay(o: any) {
    this.overlays.push(o);
  }
  addEventListener() {}
  removeEventListener() {}
  pixelToPoint(p: { x: number; y: number }) {
    return new FakePoint(p.x, p.y);
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  mapInstance = undefined as any;
});

describe('MapPanel 交互接线（FR-03，BMapGL 假实现）', () => {
  it('初始化后 setViewport 拟合默认视野包围盒（H-1）', async () => {
    vi.stubEnv('VITE_BAIDU_AK', 'fake-ak');
    (window as any).BMapGL = { Map: FakeMap, Point: FakePoint, Marker: FakeMarker, Boundary: FakeBoundary, Polygon: FakePolygon };
    const stores = storesResult({ total: 1, items: [storeItem()] });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonRes(envelope(stores))));

    const onSelectionChange = vi.fn();
    render(
      <FilterProvider>
        <MapPanel
          token="tok"
          domain={domainMeta('HQ')}
          kpi={kpiResult()}
          selectedStoreIds={[]}
          onSelectionChange={onSelectionChange}
          onOpenDetail={() => {}}
          onSessionError={() => {}}
        />
      </FilterProvider>,
    );

    await waitFor(() => expect(mapInstance.setViewportCalls.length).toBe(1));
    const vp = mapInstance.setViewportCalls[0];
    expect(vp).toHaveLength(2);
    expect(vp[0]).toBeInstanceOf(FakePoint);
  });

  it('marker 单击切换多选并上报 onSelectionChange（多选）', async () => {
    vi.stubEnv('VITE_BAIDU_AK', 'fake-ak');
    (window as any).BMapGL = { Map: FakeMap, Point: FakePoint, Marker: FakeMarker, Boundary: FakeBoundary, Polygon: FakePolygon };
    const stores = storesResult({
      total: 1,
      items: [storeItem({ store_id: 'S000001', lng_gcj02: 121.47, lat_gcj02: 31.23 })],
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonRes(envelope(stores))));

    const onSelectionChange = vi.fn();
    render(
      <FilterProvider>
        <MapPanel
          token="tok"
          domain={domainMeta('HQ')}
          kpi={kpiResult()}
          selectedStoreIds={[]}
          onSelectionChange={onSelectionChange}
          onOpenDetail={() => {}}
          onSessionError={() => {}}
        />
      </FilterProvider>,
    );

    await waitFor(() => {
      const marker = mapInstance.overlays.find((o: any) => o instanceof FakeMarker);
      expect(marker).toBeTruthy();
    });
    const marker = mapInstance.overlays.find((o: any) => o instanceof FakeMarker);
    marker.handlers.click();
    expect(onSelectionChange).toHaveBeenCalledWith(['S000001']);
  });

  it('无 AK 时降级为清单模式且不初始化地图（AC-11）', async () => {
    vi.stubEnv('VITE_BAIDU_AK', '');
    vi.stubGlobal('fetch', vi.fn());

    render(
      <FilterProvider>
        <MapPanel
          token="tok"
          domain={domainMeta('HQ')}
          kpi={kpiResult()}
          selectedStoreIds={[]}
          onSelectionChange={() => {}}
          onOpenDetail={() => {}}
          onSessionError={() => {}}
        />
      </FilterProvider>,
    );

    await waitFor(() => expect(document.body.textContent).toContain('地图不可用'));
    expect(mapInstance).toBeUndefined();
  });
});
