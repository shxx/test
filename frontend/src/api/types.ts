// 服务端契约类型（design.md §1.2 / requirement.md §7.1 字段级对应）。

export type Role = 'HQ' | 'REGION' | 'BRAND_BU';

export interface DomainInfo {
  type: 'all' | 'region' | 'brand';
  scope: string | null;
}

export interface LoginUser {
  user_id: string;
  username: string;
  display_name: string;
  role: Role;
  role_label: string;
  role_version: number;
  domain: DomainInfo;
  is_admin: boolean;
}

export interface LoginResult {
  token: string;
  token_type: string;
  issued_at: string;
  expires_at: string;
  user: LoginUser;
}

export interface DefaultViewport {
  min_lng: number | null;
  min_lat: number | null;
  max_lng: number | null;
  max_lat: number | null;
  coord: string;
}

export interface CompetitorInfo {
  count: number;
  is_approximate: boolean;
  method: string;
  note: string;
  province_basis?: number;
}

export interface DimensionInfo {
  locked: boolean;
  label: string;
  fixed_value?: string;
}

export interface YtdInfo {
  start: string;
  end: string;
  note: string;
}

export interface DomainMeta {
  user_id: string;
  username: string;
  display_name: string;
  role: Role;
  role_label: string;
  role_version: number;
  domain: DomainInfo;
  is_admin: boolean;
  provinces: string[];
  cities: string[];
  blocks: string[];
  dimensions: { region: DimensionInfo; brand: DimensionInfo };
  default_viewport: DefaultViewport;
  competitor: CompetitorInfo;
  data_version: string;
  as_of_date: string;
  ytd: YtdInfo;
  metric_notes: Record<string, unknown>;
}

export interface StoreItem {
  store_id: string;
  name: string;
  brand: string | null;
  region: string | null;
  province: string | null;
  city: string | null;
  block: string | null;
  lng_gcj02: number | null;
  lat_gcj02: number | null;
  operate_type: string | null;
  status: string | null;
  rooms: number | null;
  occ: number | null;
  adr: number | null;
  revpar: number | null;
  data_version: string;
  year: number | null;
}

export interface StoreScope {
  domain: DomainInfo;
  filters_applied: Record<string, string>;
  filter_signature: string;
  ignored_client_params: string[];
  locked_dimension_ignored: string[];
  notes: string[];
}

export interface StoresResult {
  total: number;
  page: number;
  page_size: number;
  sort: string;
  order: string;
  items: StoreItem[];
  scope: StoreScope;
}

export interface YearlyRow {
  store_id: string;
  year: number;
  available_room_nights: number | null;
  sold_room_nights: number | null;
  rooms: number | null;
  occ: number | null;
  adr: number | null;
  revpar: number | null;
}

export interface StoreDetail {
  store: StoreItem;
  yearly: YearlyRow[];
  scope: StoreScope;
}

export interface KpiResult {
  store_count: number;
  direct_count: number;
  franchise_count: number;
  city_count: number;
  province_count: number;
  revpar_median: number | null;
  revpar_valid_sample_count: number;
  weighted: Record<string, unknown>;
  metric_coverage: Record<string, number | null>;
  denominator_scope: string;
  denominator: number;
  competitor: CompetitorInfo;
  domain: DomainInfo;
  filters_applied: Record<string, string>;
  filter_signature: string;
  ignored_client_params: string[];
  locked_dimension_ignored: string[];
  notes: string[];
  data_version: string;
  as_of_date: string;
  ytd: YtdInfo;
}

export interface ExportPayload {
  filters?: Record<string, string>;
  sort?: string;
  order?: string;
  store_ids?: string[] | null;
}
