// 筛选唯一真相源：单一 FilterState，KPI/台账/地图/汇总卡/导出共用（design.md §2.3）。
// region 不进入可编辑状态（REGION 锁定只读由 dimensions 驱动展示，见 FilterAccordion）。

export type OrderDir = 'asc' | 'desc';

export interface FilterState {
  province: string | null;
  city: string | null;
  block: string | null;
  operate_type: string | null;
  sort: string;
  order: OrderDir;
  page: number;
  pageSize: number;
}

export type EditableFilterKey = 'province' | 'city' | 'block' | 'operate_type';

export type FilterAction =
  | { type: 'set'; key: EditableFilterKey; value: string | null }
  | { type: 'setSort'; sort: string; order: OrderDir }
  | { type: 'setPage'; page: number }
  | { type: 'setPageSize'; pageSize: number }
  | { type: 'reset' };

export const initialFilterState: FilterState = {
  province: null,
  city: null,
  block: null,
  operate_type: null,
  sort: 'store_id',
  order: 'asc',
  page: 1,
  pageSize: 50,
};

export function filterReducer(state: FilterState, action: FilterAction): FilterState {
  switch (action.type) {
    case 'set':
      return { ...state, [action.key]: action.value, page: 1 };
    case 'setSort':
      return { ...state, sort: action.sort, order: action.order, page: 1 };
    case 'setPage':
      return { ...state, page: action.page };
    case 'setPageSize':
      return { ...state, pageSize: action.pageSize, page: 1 };
    case 'reset':
      return initialFilterState;
    default:
      return state;
  }
}

// 仅白名单单值筛选字段；排序/分页单独透传。
export function toFilterParams(state: FilterState): Record<string, string> {
  const out: Record<string, string> = {};
  if (state.province) out.province = state.province;
  if (state.city) out.city = state.city;
  if (state.block) out.block = state.block;
  if (state.operate_type) out.operate_type = state.operate_type;
  return out;
}

export function toStoreQuery(state: FilterState): Record<string, string> {
  return {
    ...toFilterParams(state),
    sort: state.sort,
    order: state.order,
    page: String(state.page),
    page_size: String(state.pageSize),
  };
}

// KPI 不接受 page/page_size，但接受 sort/order 与筛选。
export function toKpiQuery(state: FilterState): Record<string, string> {
  return {
    ...toFilterParams(state),
    sort: state.sort,
    order: state.order,
  };
}

// 稳定的筛选指纹，用于 useLedgerData 去重（避免每次渲染重复请求）。
export function filtersFingerprint(state: FilterState): string {
  return JSON.stringify([
    state.province,
    state.city,
    state.block,
    state.operate_type,
    state.sort,
    state.order,
    state.page,
    state.pageSize,
  ]);
}

// KPI 指纹：不含 page/pageSize（聚合结果与分页无关），避免翻页冗余重拉 KPI（M-1）。
export function kpiFingerprint(state: FilterState): string {
  return JSON.stringify([
    state.province,
    state.city,
    state.block,
    state.operate_type,
    state.sort,
    state.order,
  ]);
}
