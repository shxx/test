// 筛选上下文：单一真相源，供 KPI/台账/地图/汇总卡/导出共用（design.md §2.3）。
import { createContext, useContext, useMemo, useReducer, type Dispatch, type ReactNode } from 'react';
import {
  filterReducer,
  filtersFingerprint,
  initialFilterState,
  toFilterParams,
  toKpiQuery,
  toStoreQuery,
  type FilterAction,
  type FilterState,
} from './filters';

interface FilterContextValue {
  state: FilterState;
  dispatch: Dispatch<FilterAction>;
  fingerprint: string;
  filterParams: Record<string, string>;
  storeQuery: Record<string, string>;
  kpiQuery: Record<string, string>;
}

const FilterContext = createContext<FilterContextValue | null>(null);

export function FilterProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(filterReducer, initialFilterState);
  const value = useMemo<FilterContextValue>(
    () => ({
      state,
      dispatch,
      fingerprint: filtersFingerprint(state),
      filterParams: toFilterParams(state),
      storeQuery: toStoreQuery(state),
      kpiQuery: toKpiQuery(state),
    }),
    [state],
  );
  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>;
}

export function useFilter(): FilterContextValue {
  const ctx = useContext(FilterContext);
  if (!ctx) throw new Error('useFilter must be used within FilterProvider');
  return ctx;
}
