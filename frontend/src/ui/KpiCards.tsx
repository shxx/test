// KPI 六卡（FR-04 / AC-01/03/10）：数值直接来自 /kpi，前端只格式化。
import type { KpiResult } from '../api/types';
import { formatInt, formatMetric } from '../format';

interface KpiCardsProps {
  kpi: KpiResult | null;
  loading: boolean;
}

export function KpiCards({ kpi, loading }: KpiCardsProps) {
  const competitorApproximate = kpi?.competitor?.is_approximate ?? false;
  return (
    <section className="kpi-cards" aria-label="关键指标" aria-busy={loading}>
      <article className="kpi-card">
        <h3>门店总数</h3>
        <div className="kpi-value">{formatInt(kpi?.store_count)}</div>
      </article>
      <article className="kpi-card">
        <h3>城市数</h3>
        <div className="kpi-value">{formatInt(kpi?.city_count)}</div>
      </article>
      <article className="kpi-card">
        <h3>直营 / 加盟</h3>
        <div className="kpi-value">
          {formatInt(kpi?.direct_count)} / {formatInt(kpi?.franchise_count)}
        </div>
      </article>
      <article className="kpi-card">
        <h3>省域数</h3>
        <div className="kpi-value">{formatInt(kpi?.province_count)}</div>
      </article>
      <article className="kpi-card">
        <h3>
          竞品数
          {competitorApproximate ? (
            <span className="badge badge-approximate" title={kpi?.competitor?.note}>
              近似
            </span>
          ) : null}
        </h3>
        <div className="kpi-value">{formatInt(kpi?.competitor?.count)}</div>
        {competitorApproximate && kpi?.competitor?.note ? (
          <p className="kpi-note">{kpi.competitor.note}</p>
        ) : null}
      </article>
      <article className="kpi-card">
        <h3>RevPAR 中位</h3>
        <div className="kpi-value">{formatMetric(kpi?.revpar_median)}</div>
        <p className="kpi-sub">有效样本 {formatInt(kpi?.revpar_valid_sample_count)}</p>
      </article>
    </section>
  );
}
