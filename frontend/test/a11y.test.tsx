import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { App } from '../src/App';
import { domainMeta, jsonRes, kpiResult, loginResult, storesResult } from './fixtures';

function envelope(data: unknown) {
  return { data, meta: { data_version: '2026YTD08', as_of_date: '2026-08-31' }, error: null, trace_id: 't1' };
}

function mockAppFetch(role: 'HQ' | 'REGION' = 'HQ') {
  const dm = domainMeta(role);
  const sig = 'sig-east';
  const kpi = kpiResult({ filter_signature: sig });
  const stores = storesResult({ total: 2767, scope: { ...storesResult().scope, filter_signature: sig } });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: unknown) => {
      const u = String(url);
      if (u === '/api/v1/auth/login') return jsonRes(envelope(loginResult(role)));
      if (u === '/api/v1/me/domain') return jsonRes(envelope(dm));
      if (u.startsWith('/api/v1/stores')) return jsonRes(envelope(stores));
      if (u.startsWith('/api/v1/kpi')) return jsonRes(envelope(kpi));
      return jsonRes(envelope(stores));
    }),
  );
}

async function loginAs(role: 'HQ' | 'REGION' = 'HQ') {
  render(<App />);
  await userEvent.type(await screen.findByLabelText('账号'), role.toLowerCase());
  await userEvent.type(screen.getByLabelText('口令'), 'Demo@12345');
  await userEvent.click(screen.getByRole('button', { name: '登录' }));
}

describe('a11y 自动化扫描（axe-core，无 critical/serious）', () => {
  it('登录页无 critical/serious 违规', async () => {
    mockAppFetch('HQ');
    render(<App />);
    const results = await axe.run(document.body);
    const serious = results.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious');
    expect(serious).toEqual([]);
  });

  it('HQ 主界面无 critical/serious 违规', async () => {
    mockAppFetch('HQ');
    await loginAs('HQ');
    await screen.findAllByText('13,258');
    const results = await axe.run(document.body);
    const serious = results.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious');
    expect(serious).toEqual([]);
  });
});
