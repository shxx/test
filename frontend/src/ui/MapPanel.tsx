// 区域分布地图（FR-03 / FR-10 / AC-02/04/11）：
// 点位只取服务端域内集合；权威聚合数取 /kpi 的 store_count；
// 交互：单击选中、双击下钻、框选、多选、Esc 取消、面包屑逐级回退（FR-03）；
// AK 缺失/失效/初始化异常 -> 非阻断降级，左侧省域清单继续可用（FR-10）。
import { useCallback, useEffect, useRef, useState } from 'react';
import { getStores } from '../api/client';
import { LedgerApiError } from '../api/errors';
import type { DomainMeta, KpiResult, StoreItem } from '../api/types';
import { coordKey, toBd09Cached } from '../coord/gcj02bd09';
import { useFilter } from '../state/FilterContext';
import { filtersFingerprint, toFilterParams } from '../state/filters';
import {
  addIds,
  hitTestBbox,
  normalizeBbox,
  parseBoundaryPoints,
  regionBoundaryNames,
  regionLevel,
  toggleId,
  type GeoBBox,
  type RegionLevel,
} from '../state/mapSelection';
import { formatInt } from '../format';

const MAP_MAX_POINTS = 2000;

export function loadBaiduScript(ak: string): Promise<boolean> {
  return new Promise((resolve) => {
    if (!ak) {
      resolve(false);
      return;
    }
    const w = window as unknown as { BMapGL?: unknown };
    if (w.BMapGL) {
      resolve(true);
      return;
    }
    const script = document.createElement('script');
    script.src = `https://api.map.baidu.com/api?type=webgl&v=1.0&ak=${encodeURIComponent(ak)}`;
    script.onload = () => resolve(Boolean(w.BMapGL));
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
}

// 百度 Boundary 返回形如 "lng,lat;lng,lat;..." 的坐标串，解析为点集（纯函数，便于单测）。
// 注：该纯函数定义在 state/mapSelection.ts，此处不再重复导出。

interface MapPanelProps {
  token: string;
  domain: DomainMeta;
  kpi: KpiResult | null;
  selectedStoreIds: string[];
  onSelectionChange: (ids: string[]) => void;
  onOpenDetail: (storeId: string) => void;
  onSessionError: (err: LedgerApiError) => void;
  onSignatureMismatch?: (mismatch: boolean) => void;
}

type MapAvailability = 'loading' | 'available' | 'unavailable';

export function MapPanel({
  token,
  domain,
  kpi,
  selectedStoreIds,
  onSelectionChange,
  onOpenDetail,
  onSessionError,
  onSignatureMismatch,
}: MapPanelProps) {
  const { state, dispatch } = useFilter();
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const pointsRef = useRef<StoreItem[]>([]);
  const selectionRef = useRef<Set<string>>(new Set(selectedStoreIds));
  const [availability, setAvailability] = useState<MapAvailability>('loading');
  const [points, setPoints] = useState<StoreItem[]>([]);
  const [manualListMode, setManualListMode] = useState(false);
  const fingerprint = filtersFingerprint(state);
  const level: RegionLevel = regionLevel(state.province, state.city);

  selectionRef.current = new Set(selectedStoreIds);

  const updateSelection = useCallback(
    (next: Set<string>) => {
      onSelectionChange(Array.from(next));
    },
    [onSelectionChange],
  );

  // 1) 地图脚本加载 + 初始化（失败即降级，非阻断）；视野用 setViewport 拟合包围盒（AC-02）。
  useEffect(() => {
    let cancelled = false;
    const ak = (import.meta.env.VITE_BAIDU_AK as string | undefined) ?? '';
    if (!ak) {
      setAvailability('unavailable');
      return;
    }
    setAvailability('loading');
    loadBaiduScript(ak).then((ok) => {
      if (cancelled) return;
      if (!ok) {
        setAvailability('unavailable');
        return;
      }
      try {
        const w = window as unknown as { BMapGL: any };
        const map = new w.BMapGL.Map(containerRef.current, { enableMapClick: true });
        mapRef.current = map;
        const vp = domain.default_viewport;
        if (
          vp &&
          vp.min_lng !== null &&
          vp.max_lng !== null &&
          vp.min_lat !== null &&
          vp.max_lat !== null
        ) {
          // coord 坐标系由接口下发（默认 GCJ-02）；非 GCJ-02 时不套用 GCJ-02 偏移（L-1）。
          const needConvert = (vp.coord ?? 'GCJ-02').toUpperCase() === 'GCJ-02';
          const sw = needConvert
            ? toBd09Cached(`vp|${domain.data_version}|sw`, vp.min_lng, vp.min_lat)
            : { lng: vp.min_lng, lat: vp.min_lat };
          const ne = needConvert
            ? toBd09Cached(`vp|${domain.data_version}|ne`, vp.max_lng, vp.max_lat)
            : { lng: vp.max_lng, lat: vp.max_lat };
          // 拟合包围盒而非仅居中（H-1）：setViewport 接受西南/东北两点。
          const swPt = new w.BMapGL.Point(sw.lng, sw.lat);
          const nePt = new w.BMapGL.Point(ne.lng, ne.lat);
          if (typeof map.setViewport === 'function') {
            map.setViewport([swPt, nePt]);
          } else {
            const center = new w.BMapGL.Point((sw.lng + ne.lng) / 2, (sw.lat + ne.lat) / 2);
            map.centerAndZoom(center, 6);
          }
        }
        setAvailability('available');
      } catch {
        setAvailability('unavailable');
      }
    });
    return () => {
      cancelled = true;
    };
  }, [domain.data_version, domain.default_viewport]);

  // 2) 分页拉取点位（至多 MAP_MAX_POINTS，仅视觉层，非权威计数）；
  //    并对点位响应的 filter_signature 与 /kpi 做一致性校验（H-2）。
  useEffect(() => {
    if (availability !== 'available') return;
    let cancelled = false;
    async function load() {
      const collected: StoreItem[] = [];
      let pointSignature: string | null = null;
      try {
        for (let page = 1; collected.length < MAP_MAX_POINTS; page += 1) {
          const res = await getStores(token, {
            ...toFilterParams(state),
            page: String(page),
            page_size: '200',
          });
          if (page === 1) pointSignature = res.scope.filter_signature;
          collected.push(...res.items);
          if (collected.length >= res.total || res.items.length < 200) break;
        }
      } catch (err) {
        if (err instanceof LedgerApiError) onSessionError(err);
      }
      if (!cancelled) {
        pointsRef.current = collected;
        setPoints(collected);
        onSignatureMismatch?.(
          pointSignature !== null && kpi !== null && pointSignature !== kpi.filter_signature,
        );
      }
    }
    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, fingerprint, availability]);

  // 3) 渲染 markers（单击=多选切换，双击=打开详情）+ 省/市边界几何（Boundary，最细市级；
  //    单击选中、双击下钻）。同一 effect 统一 clearOverlays 再重绘，避免 markers/边界互相覆盖。
  useEffect(() => {
    if (availability !== 'available' || !mapRef.current) return;
    const w = window as unknown as { BMapGL: any };
    const map = mapRef.current as any;
    let cancelled = false;
    try {
      map.clearOverlays();
      for (const p of points) {
        if (p.lng_gcj02 === null || p.lat_gcj02 === null) continue;
        const bd = toBd09Cached(
          coordKey(p.store_id, p.data_version, p.lng_gcj02, p.lat_gcj02),
          p.lng_gcj02,
          p.lat_gcj02,
        );
        const pt = new w.BMapGL.Point(bd.lng, bd.lat);
        const marker = new w.BMapGL.Marker(pt);
        marker.addEventListener('click', () => {
          updateSelection(toggleId(selectionRef.current, p.store_id));
        });
        marker.addEventListener('dblclick', () => onOpenDetail(p.store_id));
        map.addOverlay(marker);
      }

      if (typeof w.BMapGL?.Boundary === 'function') {
        const boundary = new w.BMapGL.Boundary();
        const names = regionBoundaryNames(level, domain.provinces, domain.cities);
        for (const name of names) {
          boundary.get(name, (rs: { boundaries?: string[] }) => {
            if (cancelled) return;
            const list = rs?.boundaries ?? [];
            for (const cs of list) {
              const pts = parseBoundaryPoints(cs);
              if (pts.length === 0) continue;
              const polygon = new w.BMapGL.Polygon(
                pts.map((p) => new w.BMapGL.Point(p.lng, p.lat)),
                {
                  strokeColor: '#1a56a0',
                  strokeWeight: 1,
                  fillColor: 'rgba(26,86,160,0.06)',
                },
              );
              const selectableLevel: RegionLevel = level === 'country' ? 'province' : 'city';
              polygon.addEventListener('click', () => {
                if (selectableLevel === 'province') {
                  dispatch({ type: 'set', key: 'province', value: name });
                  dispatch({ type: 'set', key: 'city', value: null });
                } else {
                  dispatch({ type: 'set', key: 'city', value: name });
                }
              });
              if (selectableLevel === 'province') {
                polygon.addEventListener('dblclick', () => {
                  dispatch({ type: 'set', key: 'province', value: name });
                });
              }
              map.addOverlay(polygon);
            }
          });
        }
      }
    } catch {
      setAvailability('unavailable');
    }
    return () => {
      cancelled = true;
    };
  }, [
    points,
    level,
    availability,
    domain.provinces,
    domain.cities,
    dispatch,
    onOpenDetail,
    updateSelection,
  ]);

  // 5) 框选：拖拽出矩形 -> 命中点位并入选择集合（多选累加，Esc 清空）。
  useEffect(() => {
    if (availability !== 'available' || !mapRef.current) return;
    const map = mapRef.current as any;
    let startPixel: { x: number; y: number } | null = null;

    const onDown = (e: any) => {
      const px = e?.pixel;
      if (px && Number.isFinite(px.x) && Number.isFinite(px.y)) {
        startPixel = { x: px.x, y: px.y };
      }
    };
    const onUp = (e: any) => {
      const px = e?.pixel;
      if (!startPixel || !px || !Number.isFinite(px.x) || !Number.isFinite(px.y)) {
        startPixel = null;
        return;
      }
      const dx = Math.abs(px.x - startPixel.x);
      const dy = Math.abs(px.y - startPixel.y);
      if (dx < 4 && dy < 4) {
        startPixel = null; // 点击而非拖拽，交由 marker 单击处理，避免重复计选。
        return;
      }
      try {
        const a = map.pixelToPoint(startPixel);
        const b = map.pixelToPoint(px);
        const bbox: GeoBBox = normalizeBbox(
          { lng: a.lng, lat: a.lat },
          { lng: b.lng, lat: b.lat },
        );
        // pixelToPoint 返回的是地图（BD-09）坐标：命中测试必须用同一坐标系，
        // 与 marker 渲染一致地取 BD-09 缓存换算值，避免 GCJ-02/BD-09 偏移造成误命中。
        const selectable = pointsRef.current
          .filter((p) => p.lng_gcj02 !== null && p.lat_gcj02 !== null)
          .map((p) => {
            const bd = toBd09Cached(
              coordKey(p.store_id, p.data_version, p.lng_gcj02!, p.lat_gcj02!),
              p.lng_gcj02!,
              p.lat_gcj02!,
            );
            return { id: p.store_id, lng: bd.lng, lat: bd.lat };
          });
        const hit = hitTestBbox(selectable, bbox);
        if (hit.length > 0) updateSelection(addIds(selectionRef.current, hit));
      } catch {
        /* 框选换算失败不阻断，忽略本次框选 */
      }
      startPixel = null;
    };

    map.addEventListener('mousedown', onDown);
    map.addEventListener('mouseup', onUp);
    return () => {
      map.removeEventListener?.('mousedown', onDown);
      map.removeEventListener?.('mouseup', onUp);
    };
  }, [availability, updateSelection]);

  const mapDown = availability === 'unavailable';
  const authoritative = kpi?.store_count ?? 0;
  const showListMode = mapDown || manualListMode;

  return (
    <section className="map-panel" aria-label="区域分布地图">
      <div className="map-toolbar">
        <nav className="breadcrumb" aria-label="层级面包屑">
          <button
            type="button"
            className={state.province === null ? 'crumb active' : 'crumb'}
            onClick={() => {
              dispatch({ type: 'set', key: 'province', value: null });
              dispatch({ type: 'set', key: 'city', value: null });
            }}
          >
            全国
          </button>
          {state.province ? (
            <button
              type="button"
              className={state.city === null ? 'crumb active' : 'crumb'}
              onClick={() => dispatch({ type: 'set', key: 'city', value: null })}
            >
              {state.province}
            </button>
          ) : null}
          {state.city ? <span className="crumb leaf">{state.city}</span> : null}
        </nav>
        <div className="map-toolbar-actions">
          {selectedStoreIds.length > 0 ? (
            <span className="map-selection-hint" aria-live="polite">
              已选中 {formatInt(selectedStoreIds.length)} 家（仅用于导出）
            </span>
          ) : null}
          <button type="button" onClick={() => setManualListMode((v) => !v)}>
            {manualListMode ? '返回地图模式' : '清单模式'}
          </button>
        </div>
      </div>

      {mapDown && (
        <p className="map-fallback" role="status">
          地图不可用（AK 缺失/失效或加载失败），已切换为省域清单模式；筛选、台账、详情与导出不受影响。
        </p>
      )}

      {showListMode ? (
        <div className="map-fallback-list" role="region" aria-label="省域清单等价路径">
          <p className="fallback-hint">可凭左侧「省份」清单完成同样选择与导出。</p>
          <p className="map-count" aria-live="polite">
            权威门店数：{formatInt(authoritative)}（来自 KPI）
          </p>
        </div>
      ) : (
        <>
          <div
            ref={containerRef}
            className="map-container"
            aria-label="门店分布地图"
            data-testid="map-container"
          />
          <p className="map-legend" role="note">
            单击选中 / 双击下钻 · 拖拽框选 · Esc 取消当前选择
          </p>
          {points.length < authoritative ? (
            <p className="map-count" aria-live="polite">
              已显示 {formatInt(points.length)} / 总数 {formatInt(authoritative)}（权威计数见 KPI）
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
