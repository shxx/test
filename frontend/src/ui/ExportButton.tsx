// 导出（FR-09 / AC-06/07）：与当前界面筛选同源；成功下载 CSV，
// 超限/越权/禁用均不产出文件（exportCsv 仅在 text/csv 分支返回 Blob）。
import { useState } from 'react';
import { exportCsv } from '../api/client';
import { LedgerApiError, messageFor } from '../api/errors';
import { useFilter } from '../state/FilterContext';

interface ExportButtonProps {
  token: string;
  selectedStoreIds?: string[] | null;
  onSessionError: (err: LedgerApiError) => void;
}

export function ExportButton({ token, selectedStoreIds, onSessionError }: ExportButtonProps) {
  const { state, filterParams } = useFilter();
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);

  async function handleExport() {
    if (busy) return;
    setBusy(true);
    setStatus(null);
    try {
      const payload =
        selectedStoreIds && selectedStoreIds.length > 0
          ? { store_ids: selectedStoreIds }
          : { filters: filterParams, sort: state.sort, order: state.order };
      const result = await exportCsv(token, payload);
      const url = URL.createObjectURL(result.blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = result.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setStatus({ kind: 'ok', text: `已导出 ${result.rowCount.toLocaleString('zh-CN')} 行` });
    } catch (err) {
      if (err instanceof LedgerApiError) {
        onSessionError(err);
        if (err.code === 'EXPORT_LIMIT_EXCEEDED') {
          setStatus({ kind: 'error', text: '请收窄口径：请收窄筛选条件或选区后重试。' });
        } else {
          setStatus({ kind: 'error', text: messageFor(err.code) });
        }
      } else {
        setStatus({ kind: 'error', text: '导出失败，请稍后重试' });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="export-zone">
      <button type="button" onClick={handleExport} disabled={busy}>
        {busy ? '导出中…' : '导出 CSV'}
      </button>
      {status ? (
        <p className={status.kind === 'ok' ? 'export-ok' : 'export-error'} role="status">
          {status.text}
        </p>
      ) : null}
    </div>
  );
}
