// 台账列表（FR-05）：分页、排序（白名单列）、筛选（由筛选真相源驱动）。
// 指标 null 显示「—」（含 redact_metrics / DQ 越界置空）。
import type { StoresResult } from '../api/types';
import { useFilter } from '../state/FilterContext';
import { formatMetric } from '../format';

interface LedgerTableProps {
  stores: StoresResult | null;
  loading: boolean;
  onOpenDetail: (storeId: string) => void;
}

const SORTABLE: Record<string, string> = {
  store_id: '门店编号',
  name: '门店名称',
  province: '省份',
  city: '城市',
  region: '大区',
  brand: '品牌',
  operate_type: '经营方式',
  status: '状态',
  rooms: '房量',
  occ: '出租率',
  adr: 'ADR',
  revpar: 'RevPAR',
};

export function LedgerTable({ stores, loading, onOpenDetail }: LedgerTableProps) {
  const { state, dispatch } = useFilter();
  const total = stores?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / state.pageSize));

  function toggleSort(field: string) {
    if (state.sort === field) {
      dispatch({ type: 'setSort', sort: field, order: state.order === 'asc' ? 'desc' : 'asc' });
    } else {
      dispatch({ type: 'setSort', sort: field, order: 'asc' });
    }
  }

  function sortHeader(field: string, label: string) {
    const sorted = state.sort === field;
    const ariaSort = sorted ? (state.order === 'asc' ? 'ascending' : 'descending') : 'none';
    return (
      <th scope="col" aria-sort={ariaSort === 'none' ? undefined : ariaSort}>
        <button type="button" className="sort-btn" onClick={() => toggleSort(field)}>
          {label}
          <span aria-hidden="true">{sorted ? (state.order === 'asc' ? ' ▲' : ' ▼') : ''}</span>
        </button>
      </th>
    );
  }

  return (
    <section className="ledger-table" aria-label="台账列表" aria-busy={loading}>
      <div className="table-toolbar">
        <span aria-live="polite">
          共 {total.toLocaleString('zh-CN')} 家 · 第 {stores?.page ?? state.page} 页 / 共 {totalPages} 页
        </span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {sortHeader('store_id', '门店编号')}
              {sortHeader('name', '门店名称')}
              {sortHeader('brand', '品牌')}
              {sortHeader('region', '大区')}
              {sortHeader('province', '省份')}
              {sortHeader('city', '城市')}
              {sortHeader('operate_type', '经营方式')}
              {sortHeader('status', '状态')}
              {sortHeader('rooms', '房量')}
              {sortHeader('occ', '出租率')}
              {sortHeader('adr', 'ADR')}
              {sortHeader('revpar', 'RevPAR')}
            </tr>
          </thead>
          <tbody>
            {(stores?.items ?? []).map((item) => (
              <tr key={item.store_id}>
                <td>
                  <button type="button" className="store-link" onClick={() => onOpenDetail(item.store_id)}>
                    {item.store_id}
                  </button>
                </td>
                <td>{item.name}</td>
                <td>{item.brand ?? '—'}</td>
                <td>{item.region ?? '—'}</td>
                <td>{item.province ?? '—'}</td>
                <td>{item.city ?? '—'}</td>
                <td>{item.operate_type ?? '—'}</td>
                <td>{item.status ?? '—'}</td>
                <td>{formatMetric(item.rooms, 0)}</td>
                <td>{formatMetric(item.occ)}</td>
                <td>{formatMetric(item.adr)}</td>
                <td>{formatMetric(item.revpar)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <nav className="pagination" aria-label="分页">
        <button
          type="button"
          disabled={state.page <= 1}
          onClick={() => dispatch({ type: 'setPage', page: state.page - 1 })}
        >
          上一页
        </button>
        <button
          type="button"
          disabled={state.page >= totalPages}
          onClick={() => dispatch({ type: 'setPage', page: state.page + 1 })}
        >
          下一页
        </button>
      </nav>
    </section>
  );
}
