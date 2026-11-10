// 台账 + KPI 同源刷新：携带相同筛选参数，filter_signature 一致性断言（design.md §2.3）。
// KPI 与台账分页解耦：翻页只重拉台账，KPI 仅在筛选/排序变化时刷新（M-1）。
import { useEffect, useMemo, useState } from 'react';
import { getKpi, getStores } from '../api/client';
import { LedgerApiError } from '../api/errors';
import type { KpiResult, StoresResult } from '../api/types';
import type { FilterState } from './filters';
import { filtersFingerprint, kpiFingerprint, toKpiQuery, toStoreQuery } from './filters';

export interface LedgerData {
  stores: StoresResult | null;
  kpi: KpiResult | null;
  loading: boolean;
  error: LedgerApiError | null;
  signaturesConsistent: boolean;
}

export function useLedgerData(
  token: string,
  state: FilterState,
  onSessionError: (err: LedgerApiError) => void,
): LedgerData {
  const [stores, setStores] = useState<StoresResult | null>(null);
  const [kpi, setKpi] = useState<KpiResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<LedgerApiError | null>(null);

  const storeFingerprint = filtersFingerprint(state);
  const kpiFp = kpiFingerprint(state);

  // KPI：仅随筛选/排序变化刷新（不含分页）。
  useEffect(() => {
    let cancelled = false;
    getKpi(token, toKpiQuery(state))
      .then((k) => {
        if (cancelled) return;
        setKpi(k);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const apiErr =
          err instanceof LedgerApiError ? err : new LedgerApiError('INTERNAL_ERROR', '服务内部错误', 500, null);
        onSessionError(apiErr);
        setError(apiErr);
        setKpi(null);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, kpiFp]);

  // 台账：随筛选/排序/分页变化刷新。
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getStores(token, toStoreQuery(state))
      .then((s) => {
        if (cancelled) return;
        setStores(s);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const apiErr =
          err instanceof LedgerApiError ? err : new LedgerApiError('INTERNAL_ERROR', '服务内部错误', 500, null);
        // 401/NO_VALID_DOMAIN 等会话级错误上抛；其余（越权/非法筛选）就地展示。
        onSessionError(apiErr);
        setStores(null);
        setError(apiErr);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, storeFingerprint]);

  const signaturesConsistent = useMemo(() => {
    if (!stores || !kpi) return true;
    return stores.scope.filter_signature === kpi.filter_signature;
  }, [stores, kpi]);

  return { stores, kpi, loading, error, signaturesConsistent };
}
