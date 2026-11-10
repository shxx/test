// 单店详情抽屉（FR-06 / AC-06）：dialog + aria-modal + 焦点陷阱 + Esc + 焦点归还。
// 越权/不存在统一「超出数据域」，不回显域外字段。
import { useEffect, useRef, useState } from 'react';
import { getStoreDetail } from '../api/client';
import { LedgerApiError, messageFor } from '../api/errors';
import type { StoreDetail } from '../api/types';
import { formatMetric } from '../format';
import { trapFocus } from '../a11y/focusTrap';

interface StoreDrawerProps {
  token: string;
  storeId: string;
  onClose: () => void;
  onSessionError: (err: LedgerApiError) => void;
}

export function StoreDrawer({ token, storeId, onClose, onSessionError }: StoreDrawerProps) {
  const [detail, setDetail] = useState<StoreDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    setLoading(true);
    setError(null);
    setDetail(null);

    getStoreDetail(token, storeId)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoading(false);
        if (err instanceof LedgerApiError) {
          onSessionError(err);
          setError(messageFor(err.code));
        } else {
          setError('加载失败');
        }
      });

    // 打开时把焦点移入抽屉
    requestAnimationFrame(() => {
      const panel = panelRef.current;
      if (panel) {
        const first = panel.querySelector<HTMLElement>('button, [href], input, select, textarea');
        (first ?? panel).focus();
      }
    });

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }
      if (panelRef.current) trapFocus(panelRef.current, e);
    }

    document.addEventListener('keydown', onKeyDown);
    return () => {
      cancelled = true;
      document.removeEventListener('keydown', onKeyDown);
      previouslyFocused?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, storeId]);

  const store = detail?.store;
  const titleId = 'store-drawer-title';

  return (
    <div className="drawer-backdrop" role="presentation" onClick={onClose}>
      <div
        className="drawer-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={panelRef}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="drawer-header">
          <h2 id={titleId}>{store ? `${store.name}（${store.store_id}）` : '门店详情'}</h2>
          <button type="button" onClick={onClose} aria-label="关闭详情">
            关闭
          </button>
        </div>
        <div className="drawer-body">
          {loading ? (
            <p aria-live="polite">加载中…</p>
          ) : error ? (
            <p className="drawer-error" role="alert">
              {error}
            </p>
          ) : store ? (
            <>
              <dl className="detail-grid">
                <dt>品牌</dt>
                <dd>{store.brand ?? '—'}</dd>
                <dt>大区</dt>
                <dd>{store.region ?? '—'}</dd>
                <dt>省份</dt>
                <dd>{store.province ?? '—'}</dd>
                <dt>城市</dt>
                <dd>{store.city ?? '—'}</dd>
                <dt>区块</dt>
                <dd>{store.block ?? '—'}</dd>
                <dt>经营方式</dt>
                <dd>{store.operate_type ?? '—'}</dd>
                <dt>状态</dt>
                <dd>{store.status ?? '—'}</dd>
                <dt>房量</dt>
                <dd>{formatMetric(store.rooms, 0)}</dd>
                <dt>出租率</dt>
                <dd>{formatMetric(store.occ)}</dd>
                <dt>ADR</dt>
                <dd>{formatMetric(store.adr)}</dd>
                <dt>RevPAR</dt>
                <dd>{formatMetric(store.revpar)}</dd>
              </dl>
              <h3>逐年经营</h3>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">年份</th>
                      <th scope="col">房量</th>
                      <th scope="col">出租率</th>
                      <th scope="col">ADR</th>
                      <th scope="col">RevPAR</th>
                      <th scope="col">可售房晚</th>
                      <th scope="col">售出房晚</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(detail?.yearly ?? []).map((y) => (
                      <tr key={y.year}>
                        <td>{y.year}</td>
                        <td>{formatMetric(y.rooms, 0)}</td>
                        <td>{formatMetric(y.occ)}</td>
                        <td>{formatMetric(y.adr)}</td>
                        <td>{formatMetric(y.revpar)}</td>
                        <td>{formatMetric(y.available_room_nights, 0)}</td>
                        <td>{formatMetric(y.sold_room_nights, 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
