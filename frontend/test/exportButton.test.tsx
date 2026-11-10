import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FilterProvider } from '../src/state/FilterContext';
import { ExportButton } from '../src/ui/ExportButton';
import { jsonRes } from './fixtures';

function errorEnvelope(code: string, message: string) {
  return { data: null, meta: {}, error: { code, message }, trace_id: 't1' };
}

function renderExport(selectedStoreIds?: string[]) {
  const fetchMock = vi.fn().mockResolvedValue(
    jsonRes(errorEnvelope('EXPORT_LIMIT_EXCEEDED', '请收窄口径'), 422),
  );
  vi.stubGlobal('fetch', fetchMock);
  render(
    <FilterProvider>
      <ExportButton token="tok" selectedStoreIds={selectedStoreIds} onSessionError={() => {}} />
    </FilterProvider>,
  );
  return fetchMock;
}

function exportBody(fetchMock: ReturnType<typeof vi.fn>) {
  const call = fetchMock.mock.calls.find((c) => String(c[0]) === '/api/v1/exports');
  expect(call).toBeTruthy();
  return JSON.parse(String(call![1]!.body));
}

describe('ExportButton 选择集合 → store_ids 导出链路（FR-09 / B-2）', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('有选择时请求体携带 store_ids（不携带 filters/sort/order）', async () => {
    const fn = renderExport(['S000001', 'S000002']);
    await userEvent.click(screen.getByRole('button', { name: '导出 CSV' }));

    expect(exportBody(fn)).toEqual({ store_ids: ['S000001', 'S000002'] });
  });

  it('无选择时请求体携带 filters/sort/order（不携带 store_ids）', async () => {
    const fn = renderExport();
    await userEvent.click(screen.getByRole('button', { name: '导出 CSV' }));

    const body = exportBody(fn);
    expect(body.filters).toBeDefined();
    expect(body.sort).toBe('store_id');
    expect(body.order).toBe('asc');
    expect(body.store_ids).toBeUndefined();
  });

  it('有选择时展示「导出仅包含所选门店」提示', async () => {
    renderExport(['S000001']);
    expect(await screen.findByText(/导出仅包含所选门店/)).toBeInTheDocument();
  });

  it('无选择时展示「按当前筛选口径导出」提示', () => {
    renderExport();
    expect(screen.getByText('按当前筛选口径导出')).toBeInTheDocument();
  });
});
