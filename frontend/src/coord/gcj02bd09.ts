// GCJ-02 -> BD-09 纯前端换算（标准公开公式，含非线性偏移项），无网络、不调后端。
// 记忆化 + 计数，用于断言「重复渲染不触发二次换算」（requirement.md §6.3 / design.md §2.5）。

export interface Bd09 {
  lng: number;
  lat: number;
}

const X_PI = (Math.PI * 3000.0) / 180.0;

const cache = new Map<string, Bd09>();
let computeCount = 0;

export function gcj02ToBd09(lng: number, lat: number): Bd09 {
  const z = Math.sqrt(lng * lng + lat * lat) + 0.00002 * Math.sin(lat * X_PI);
  const theta = Math.atan2(lat, lng) + 0.000003 * Math.cos(lng * X_PI);
  return {
    lng: z * Math.cos(theta) + 0.0065,
    lat: z * Math.sin(theta) + 0.006,
  };
}

// 缓存键含 data_version：口径切换时由上层 resetCoordCache() 清空，防止串坐标。
export function toBd09Cached(key: string, lng: number, lat: number): Bd09 {
  const hit = cache.get(key);
  if (hit) return hit;
  computeCount += 1;
  const value = gcj02ToBd09(lng, lat);
  cache.set(key, value);
  return value;
}

export function coordKey(storeId: string, dataVersion: string, lng: number, lat: number): string {
  return `${storeId}|${dataVersion}|${lng}|${lat}`;
}

export function resetCoordCache(): void {
  cache.clear();
}

export function coordComputeCount(): number {
  return computeCount;
}

export function resetCoordComputeCount(): void {
  computeCount = 0;
}
