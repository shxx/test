import { describe, expect, it } from 'vitest';
import {
  filterReducer,
  initialFilterState,
  toFilterParams,
  toKpiQuery,
  toStoreQuery,
} from '../src/state/filters';

describe('filterReducer', () => {
  it('sets a filter and resets page', () => {
    const s = filterReducer({ ...initialFilterState, page: 5 }, { type: 'set', key: 'province', value: '上海' });
    expect(s.province).toBe('上海');
    expect(s.page).toBe(1);
  });

  it('clears a filter with null', () => {
    const s = filterReducer({ ...initialFilterState, province: '上海' }, { type: 'set', key: 'province', value: null });
    expect(s.province).toBeNull();
  });

  it('toggles sort order', () => {
    const s1 = filterReducer(initialFilterState, { type: 'setSort', sort: 'name', order: 'asc' });
    expect(s1.sort).toBe('name');
    const s2 = filterReducer(s1, { type: 'setSort', sort: 'name', order: 'desc' });
    expect(s2.order).toBe('desc');
  });

  it('reset restores initial state', () => {
    const s = filterReducer({ ...initialFilterState, province: '上海' }, { type: 'reset' });
    expect(s).toEqual(initialFilterState);
  });
});

describe('query builders', () => {
  it('toFilterParams only includes non-null single-value filters', () => {
    const params = toFilterParams({ ...initialFilterState, province: '上海', operate_type: '直营' });
    expect(params).toEqual({ province: '上海', operate_type: '直营' });
  });

  it('toStoreQuery includes paging/sort; toKpiQuery omits paging', () => {
    const state = { ...initialFilterState, province: '上海', page: 2, pageSize: 100, sort: 'revpar', order: 'desc' as const };
    expect(toStoreQuery(state)).toEqual({
      province: '上海',
      sort: 'revpar',
      order: 'desc',
      page: '2',
      page_size: '100',
    });
    expect(toKpiQuery(state)).toEqual({ province: '上海', sort: 'revpar', order: 'desc' });
  });
});
