// 台账 + KPI 同源刷新：携带相同筛选参数，filter_signature 一致性断言（design.md §2.3）。
import { useEffect, useState } from 'react';
import { getKpi, getStores } from '../api/client';
import { LedgerApiError } from '../api/errors';
import type { KpiResult, StoresResult } from '../api/types';
import type { FilterState } from './filters';
import { filtersFingerprint, toKpiQuery, toStoreQuery } from './filters';

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
  const [data, setData] = useState<LedgerData>({
    stores: null,
    kpi: null,
    loading: true,
    error: null,
    signaturesConsistent: true,
  });

  const fingerprint = filtersFingerprint(state);

  useEffect(() => {
    let cancelled = false;
    setData((prev) => ({ ...prev, loading: true, error: null }));
    const storeQuery = toStoreQuery(state);
    const kpiQuery = toKpiQuery(state);
    Promise.all([getStores(token, storeQuery), getKpi(token, kpiQuery)])
      .then(([stores, kpi]) => {
        if (cancelled) return;
        const signaturesConsistent = stores.scope.filter_signature === kpi.filter_signature;
        setData({ stores, kpi, loading: false, error: null, signaturesConsistent });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const apiErr =
          err instanceof LedgerApiError ? err : new LedgerApiError('INTERNAL_ERROR', '服务内部错误', 500, null);
        // 401/NO_VALID_DOMAIN 等会话级错误上抛；其余（越权/非法筛选）就地展示。
        onSessionError(apiErr);
        setData({ stores: null, kpi: null, loading: false, error: apiErr, signaturesConsistent: true });
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, fingerprint]);

  return data;
}
