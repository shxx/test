// 地图选择纯逻辑（FR-03）：框选命中、多选切换、下钻层级——与百度 SDK 解耦，便于单测。
// 仅描述「选择集合」与「层级」两个纯状态，不做任何网络/权限裁决；数据域安全边界由服务端裁决。

export interface GeoPoint {
  lng: number;
  lat: number;
}

export interface GeoBBox {
  minLng: number;
  minLat: number;
  maxLng: number;
  maxLat: number;
}

// 门店点命中框选使用 GCJ-02 原始坐标（点位加载自 /stores 的 lng_gcj02/lat_gcj02）。
export interface SelectablePoint {
  id: string;
  lng: number;
  lat: number;
}

// 多选：点击切换单个 id 的选中态（Set 保证不重复、可累积）。
export function toggleId(ids: ReadonlySet<string>, id: string): Set<string> {
  const next = new Set(ids);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

// 框选/批量：并入一组 id（框选为累加语义，Esc 清空，见 App 的 Esc 处理）。
export function addIds(ids: ReadonlySet<string>, toAdd: Iterable<string>): Set<string> {
  const next = new Set(ids);
  for (const id of toAdd) next.add(id);
  return next;
}

export function clearIds(): Set<string> {
  return new Set();
}

// 百度 Boundary 返回形如 "lng,lat;lng,lat;..." 的坐标串，解析为点集（纯函数，便于单测）。
export function parseBoundaryPoints(coordString: string): Array<{ lng: number; lat: number }> {
  if (!coordString) return [];
  return coordString
    .split(';')
    .map((s) => {
      const [lng, lat] = s.split(',').map((n) => Number(n));
      return { lng, lat };
    })
    .filter((p) => Number.isFinite(p.lng) && Number.isFinite(p.lat));
}

export function normalizeBbox(a: GeoPoint, b: GeoPoint): GeoBBox {
  return {
    minLng: Math.min(a.lng, b.lng),
    minLat: Math.min(a.lat, b.lat),
    maxLng: Math.max(a.lng, b.lng),
    maxLat: Math.max(a.lat, b.lat),
  };
}

// 框选命中：返回落在包围盒内的门店 id（含边界）。
export function hitTestBbox(points: ReadonlyArray<SelectablePoint>, bbox: GeoBBox): string[] {
  return points
    .filter(
      (p) =>
        p.lng >= bbox.minLng && p.lng <= bbox.maxLng && p.lat >= bbox.minLat && p.lat <= bbox.maxLat,
    )
    .map((p) => p.id);
}

// 层级：全国 -> 省 -> 市，最细市级（不渲染区县/商圈边界）。
export type RegionLevel = 'country' | 'province' | 'city';

export function regionLevel(province: string | null, city: string | null): RegionLevel {
  if (city) return 'city';
  if (province) return 'province';
  return 'country';
}

// 双击下钻目标层级：市为最细层，不再下钻。
export function drillTarget(level: RegionLevel): RegionLevel | null {
  if (level === 'country') return 'province';
  if (level === 'province') return 'city';
  return null;
}

// 面包屑逐级回退（Esc / 点击面包屑）：市 -> 省 -> 全国。
export function stepBackLevel(level: RegionLevel): RegionLevel {
  if (level === 'city') return 'province';
  return 'country';
}

// 各层级要渲染的行政区边界名称：
// 全国层渲染省界；省/市层渲染城市边界（最细市级）。cities 为域级扁平清单（G5 缺口，无省属关系）。
export function regionBoundaryNames(
  level: RegionLevel,
  provinces: ReadonlyArray<string>,
  cities: ReadonlyArray<string>,
): string[] {
  if (level === 'country') return [...provinces];
  return [...cities];
}
