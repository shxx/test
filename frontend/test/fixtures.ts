// 测试共享数据工厂与 fetch 响应桩。
import type {
  DomainMeta,
  KpiResult,
  LoginResult,
  StoreDetail,
  StoresResult,
} from '../src/api/types';

export const ALL_PROVINCES = [
  '北京', '天津', '河北', '山西', '内蒙古', '辽宁', '吉林', '黑龙江',
  '上海', '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南',
  '湖北', '湖南', '广东', '广西', '海南', '重庆', '四川', '贵州',
  '云南', '西藏', '陕西', '甘肃', '青海', '宁夏', '新疆', '香港',
  '澳门', '台湾',
];

export const EAST_PROVINCES = ['上海', '江苏', '浙江', '安徽', '福建', '江西'];

export function loginResult(role: 'HQ' | 'REGION' | 'BRAND_BU' = 'HQ'): LoginResult {
  return {
    token: 'token-' + role,
    token_type: 'Bearer',
    issued_at: '2026-11-09T00:00:00+00:00',
    expires_at: '2026-11-09T08:00:00+00:00',
    user: {
      user_id: 'u_' + role.toLowerCase(),
      username: role.toLowerCase(),
      display_name: role === 'HQ' ? '总部用户' : '演示用户',
      role,
      role_label: role === 'HQ' ? '总部' : role === 'REGION' ? '大区' : '品牌BU',
      role_version: 1,
      domain: { type: role === 'HQ' ? 'all' : role === 'REGION' ? 'region' : 'brand', scope: role === 'HQ' ? null : '华东' },
      is_admin: false,
    },
  };
}

export function domainMeta(role: 'HQ' | 'REGION' | 'BRAND_BU' = 'HQ'): DomainMeta {
  const regionLocked = role === 'REGION';
  return {
    user_id: 'u_' + role.toLowerCase(),
    username: role.toLowerCase(),
    display_name: role === 'HQ' ? '总部用户' : '演示用户',
    role,
    role_label: role === 'HQ' ? '总部' : role === 'REGION' ? '大区' : '品牌BU',
    role_version: 1,
    domain: { type: role === 'HQ' ? 'all' : role === 'REGION' ? 'region' : 'brand', scope: role === 'HQ' ? null : role === 'REGION' ? '华东' : '欢朋' },
    is_admin: false,
    provinces: role === 'REGION' ? EAST_PROVINCES : ALL_PROVINCES,
    cities: role === 'REGION' ? ['上海01市', '江苏01市', '浙江01市'] : ['上海01市', '北京01市'],
    blocks: ['核心商圈', '次核心商圈'],
    dimensions: {
      region: regionLocked
        ? { locked: true, label: '已锁定', fixed_value: '华东' }
        : { locked: false, label: '可选' },
      brand: { locked: false, label: '可选' },
    },
    default_viewport: { min_lng: 118, min_lat: 27, max_lng: 122, max_lat: 33, coord: 'GCJ-02' },
    competitor: role === 'HQ'
      ? { count: 47726, is_approximate: false, method: 'exact', note: '总部为全量精确计数' }
      : { count: 1234, is_approximate: true, method: 'province_mapping', note: '竞品表无 region 字段，属近似口径' },
    data_version: '2026YTD08',
    as_of_date: '2026-08-31',
    ytd: { start: '2026-01', end: '2026-08', note: '与完整年比较需注意季节性' },
    metric_notes: {},
  };
}

export function storeItem(overrides: Partial<import('../src/api/types').StoreItem> = {}): import('../src/api/types').StoreItem {
  return {
    store_id: 'S000001',
    name: '门店000001',
    brand: '其他品牌',
    region: '华东',
    province: '上海',
    city: '上海01市',
    block: '核心商圈',
    lng_gcj02: 121.47,
    lat_gcj02: 31.23,
    operate_type: '直营',
    status: '在营',
    rooms: 100,
    occ: 0.6,
    adr: 300,
    revpar: 180,
    data_version: '2026YTD08',
    year: 2026,
    ...overrides,
  };
}

export function storesResult(overrides: Partial<StoresResult> = {}): StoresResult {
  return {
    total: 13258,
    page: 1,
    page_size: 50,
    sort: 'store_id',
    order: 'asc',
    items: [storeItem()],
    scope: {
      domain: { type: 'all', scope: null },
      filters_applied: {},
      filter_signature: 'sig-abc',
      ignored_client_params: [],
      locked_dimension_ignored: [],
      notes: [],
    },
    ...overrides,
  };
}

export function kpiResult(overrides: Partial<KpiResult> = {}): KpiResult {
  return {
    store_count: 13258,
    direct_count: 429,
    franchise_count: 12829,
    city_count: 365,
    province_count: 34,
    revpar_median: 180,
    revpar_valid_sample_count: 13258,
    weighted: {},
    metric_coverage: {},
    denominator_scope: '当前口径',
    denominator: 13258,
    competitor: { count: 47726, is_approximate: false, method: 'exact', note: '总部为全量精确计数' },
    domain: { type: 'all', scope: null },
    filters_applied: {},
    filter_signature: 'sig-abc',
    ignored_client_params: [],
    locked_dimension_ignored: [],
    notes: [],
    data_version: '2026YTD08',
    as_of_date: '2026-08-31',
    ytd: { start: '2026-01', end: '2026-08', note: '与完整年比较需注意季节性' },
    ...overrides,
  };
}

export function storeDetail(overrides: Partial<StoreDetail> = {}): StoreDetail {
  return {
    store: storeItem(),
    yearly: [
      { store_id: 'S000001', year: 2024, available_room_nights: 36500, sold_room_nights: 21900, rooms: 100, occ: 0.6, adr: 300, revpar: 180 },
      { store_id: 'S000001', year: 2025, available_room_nights: 36500, sold_room_nights: 21900, rooms: 100, occ: 0.6, adr: 300, revpar: 180 },
      { store_id: 'S000001', year: 2026, available_room_nights: 36500, sold_room_nights: 21900, rooms: 100, occ: 0.6, adr: 300, revpar: 180 },
    ],
    scope: { domain: { type: 'all', scope: null }, filters_applied: {}, filter_signature: 'sig-abc', ignored_client_params: [], locked_dimension_ignored: [], notes: [] },
    ...overrides,
  };
}

export function jsonRes(body: unknown, status = 200, extraHeaders: Record<string, string> = {}): Response {
  const headers = new Map<string, string>(
    Object.entries({ 'content-type': 'application/json; charset=utf-8', ...extraHeaders }).map(([k, v]) => [k.toLowerCase(), v]),
  );
  const text = JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (k: string) => headers.get(k.toLowerCase()) ?? null },
    json: async () => body,
    text: async () => text,
    blob: async () => new Blob([text]),
  } as unknown as Response;
}

export function csvRes(content: string, extraHeaders: Record<string, string> = {}): Response {
  const headers = new Map<string, string>(
    Object.entries({ 'content-type': 'text/csv; charset=utf-8', ...extraHeaders }).map(([k, v]) => [k.toLowerCase(), v]),
  );
  return {
    ok: true,
    status: 200,
    headers: { get: (k: string) => headers.get(k.toLowerCase()) ?? null },
    json: async () => {
      throw new Error('not json');
    },
    text: async () => content,
    blob: async () => new Blob([content]),
  } as unknown as Response;
}
