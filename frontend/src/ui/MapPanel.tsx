// 区域分布地图（FR-03 / FR-10 / AC-02/04/11）：
// 点位只取服务端域内集合；权威聚合数取 /kpi 的 store_count；
// AK 缺失/失效/初始化异常 -> 非阻断降级，左侧省域清单继续可用。
import { useEffect, useRef, useState } from 'react';
import { getStores } from '../api/client';
import { LedgerApiError } from '../api/errors';
import type { DomainMeta, KpiResult, StoreItem } from '../api/types';
import { coordKey, toBd09Cached } from '../coord/gcj02bd09';
import { useFilter } from '../state/FilterContext';
import { filtersFingerprint, toFilterParams } from '../state/filters';
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

interface MapPanelProps {
  token: string;
  domain: DomainMeta;
  kpi: KpiResult | null;
  onOpenDetail: (storeId: string) => void;
  onSessionError: (err: LedgerApiError) => void;
  onSelectedCountChange?: (n: number) => void;
}

type MapAvailability = 'loading' | 'available' | 'unavailable';

export function MapPanel({
  token,
  domain,
  kpi,
  onOpenDetail,
  onSessionError,
  onSelectedCountChange,
}: MapPanelProps) {
  const { state, dispatch } = useFilter();
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<unknown>(null);
  const [availability, setAvailability] = useState<MapAvailability>('loading');
  const [points, setPoints] = useState<StoreItem[]>([]);
  const [manualListMode, setManualListMode] = useState(false);
  const fingerprint = filtersFingerprint(state);

  // 1) 地图脚本加载 + 初始化（失败即降级，非阻断）
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
          const sw = toBd09Cached(`vp|${domain.data_version}|sw`, vp.min_lng, vp.min_lat);
          const ne = toBd09Cached(`vp|${domain.data_version}|ne`, vp.max_lng, vp.max_lat);
          const center = new w.BMapGL.Point((sw.lng + ne.lng) / 2, (sw.lat + ne.lat) / 2);
          map.centerAndZoom(center, 6);
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

  // 2) 分页拉取点位（至多 MAP_MAX_POINTS，仅视觉层，非权威计数）
  useEffect(() => {
    if (availability !== 'available') return;
    let cancelled = false;
    async function load() {
      const collected: StoreItem[] = [];
      try {
        for (let page = 1; collected.length < MAP_MAX_POINTS; page += 1) {
          const res = await getStores(token, {
            ...toFilterParams(state),
            page: String(page),
            page_size: '200',
          });
          collected.push(...res.items);
          if (collected.length >= res.total || res.items.length < 200) break;
        }
      } catch (err) {
        if (err instanceof LedgerApiError) onSessionError(err);
      }
      if (!cancelled) setPoints(collected);
    }
    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, fingerprint, availability]);

  // 3) 渲染 markers（GCJ-02 -> BD-09 缓存换算）
  useEffect(() => {
    if (availability !== 'available' || !mapRef.current) return;
    const w = window as unknown as { BMapGL: any };
    const map = mapRef.current as any;
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
        marker.addEventListener('click', () => onOpenDetail(p.store_id));
        map.addOverlay(marker);
      }
    } catch {
      setAvailability('unavailable');
    }
  }, [points, availability, onOpenDetail]);

  // 框选/多选仅用于导出（G1/G2）：以「已显示点数」作为本地计数，不替代权威汇总。
  useEffect(() => {
    onSelectedCountChange?.(points.length);
  }, [points, onSelectedCountChange]);

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
            onClick={() => dispatch({ type: 'set', key: 'province', value: null })}
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
        <button type="button" onClick={() => setManualListMode((v) => !v)}>
          {manualListMode ? '返回地图模式' : '清单模式'}
        </button>
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
            role="application"
            aria-label="门店分布地图"
            data-testid="map-container"
          />
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
