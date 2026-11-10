// 选区汇总卡（FR-08 / AC-03）：权威汇总取自携带相同筛选参数的 /kpi，
// 「已选 N 项」仅作本地 UI 计数，不用前端聚合替代服务端汇总。
import type { KpiResult } from '../api/types';
import { formatInt } from '../format';

interface SummaryCardProps {
  kpi: KpiResult | null;
  loading: boolean;
  selectedCount?: number | null;
}

export function SummaryCard({ kpi, loading, selectedCount }: SummaryCardProps) {
  const approximate = kpi?.competitor?.is_approximate ?? false;
  return (
    <section className="summary-card" aria-label="选区汇总" aria-busy={loading}>
      <h3>选区汇总</h3>
      <dl className="summary-grid">
        <div>
          <dt>门店数</dt>
          <dd>{formatInt(kpi?.store_count)}</dd>
        </div>
        <div>
          <dt>直营 / 加盟</dt>
          <dd>
            {formatInt(kpi?.direct_count)} / {formatInt(kpi?.franchise_count)}
          </dd>
        </div>
        <div>
          <dt>覆盖省 / 市</dt>
          <dd>
            {formatInt(kpi?.province_count)} / {formatInt(kpi?.city_count)}
          </dd>
        </div>
        <div>
          <dt>
            竞品
            {approximate ? <span className="badge badge-approximate">近似</span> : null}
          </dt>
          <dd>{formatInt(kpi?.competitor?.count)}</dd>
        </div>
      </dl>
      {selectedCount !== null && selectedCount !== undefined ? (
        <p className="selected-count" aria-live="polite">
          已选中 {formatInt(selectedCount)} 项（仅用于导出）
        </p>
      ) : null}
    </section>
  );
}
