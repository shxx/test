import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '../src/App';
import {
  ALL_PROVINCES,
  EAST_PROVINCES,
  domainMeta,
  jsonRes,
  kpiResult,
  loginResult,
  storesResult,
} from './fixtures';

function envelope(data: unknown) {
  return { data, meta: { data_version: '2026YTD08', as_of_date: '2026-08-31' }, error: null, trace_id: 't1' };
}
function errorEnvelope(code: string, message: string) {
  return { data: null, meta: {}, error: { code, message }, trace_id: 't1' };
}

type Role = 'HQ' | 'REGION' | 'BRAND_BU';

function mockAppFetch(role: Role, extra: { exportError?: string } = {}) {
  const dm = domainMeta(role);
  const sig = 'sig-east';
  const kpi = kpiResult(
    role === 'REGION'
      ? {
          store_count: 2767,
          direct_count: 160,
          franchise_count: 2607,
          city_count: 100,
          province_count: 6,
          competitor: dm.competitor,
          domain: dm.domain,
          filter_signature: sig,
        }
      : {},
  );
  const stores = storesResult(
    role === 'REGION'
      ? { total: 2767, scope: { ...storesResult().scope, domain: dm.domain, filter_signature: sig } }
      : {},
  );

  const fn = vi.fn(async (url: unknown, init?: RequestInit) => {
    const u = String(url);
    const method = init?.method ?? 'GET';
    if (u === '/api/v1/auth/login') return jsonRes(envelope(loginResult(role)));
    if (u === '/api/v1/me/domain') return jsonRes(envelope(dm));
    if (u.startsWith('/api/v1/exports')) {
      return jsonRes(errorEnvelope(extra.exportError ?? 'EXPORT_LIMIT_EXCEEDED', '请收窄口径'), 422);
    }
    if (u.startsWith('/api/v1/stores/')) {
      return jsonRes(errorEnvelope('OUT_OF_DOMAIN', '超出数据域'), 403);
    }
    if (u.startsWith('/api/v1/stores')) return jsonRes(envelope(stores));
    if (u.startsWith('/api/v1/kpi')) return jsonRes(envelope(kpi));
    return jsonRes(errorEnvelope('NOT_FOUND', '资源不存在'), 404);
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

async function loginAs(role: Role) {
  render(<App />);
  await userEvent.type(await screen.findByLabelText('账号'), role.toLowerCase());
  await userEvent.type(screen.getByLabelText('口令'), 'Demo@12345');
  await userEvent.click(screen.getByRole('button', { name: '登录' }));
}

describe('App 集成（AC 映射）', () => {
  it('AC-01 HQ 登录：KPI 门店 13,258、省域 34 项、竞品无「近似」标注', async () => {
    mockAppFetch('HQ');
    await loginAs('HQ');

    expect((await screen.findAllByText('13,258')).length).toBeGreaterThan(0);
    expect(screen.getByText('34')).toBeInTheDocument(); // 省域数
    expect(screen.queryByText('近似')).not.toBeInTheDocument();

    const provinceRadios = document.querySelectorAll('input[name="filter-province"]');
    expect(provinceRadios.length).toBe(ALL_PROVINCES.length + 1); // 全部 + 34 省
  });

  it('AC-02/05 REGION 登录：省域仅 6 项、大区锁定只读并标注「已锁定」', async () => {
    mockAppFetch('REGION');
    await loginAs('REGION');

    expect((await screen.findAllByText('2,767')).length).toBeGreaterThan(0);

    const provinceRadios = document.querySelectorAll('input[name="filter-province"]');
    expect(provinceRadios.length).toBe(EAST_PROVINCES.length + 1); // 全部 + 6 省

    const locked = document.querySelector('.locked-value');
    expect(locked).toHaveTextContent('华东');
    expect(screen.getAllByText('已锁定').length).toBeGreaterThan(0);
  });

  it('AC-11 地图不可用：显示非阻断降级提示，筛选/台账仍可用', async () => {
    mockAppFetch('HQ');
    await loginAs('HQ');

    expect(await screen.findByText(/地图不可用/)).toBeInTheDocument();
    expect(screen.getByLabelText('筛选条件')).toBeInTheDocument();
    expect(screen.getByLabelText('台账列表')).toBeInTheDocument();
  });

  it('AC-06/07 导出超限：提示「请收窄口径」且不产出文件', async () => {
    mockAppFetch('HQ');
    await loginAs('HQ');

    await screen.findAllByText('13,258');
    await userEvent.click(screen.getByRole('button', { name: '导出 CSV' }));

    expect(await screen.findByText(/请收窄口径/)).toBeInTheDocument();
    // 拒绝路径不得产出任何下载文件（无 <a download>）。
    expect(document.querySelector('a[download]')).toBeNull();
  });

  it('AC-08 角色变更：任一请求 401 ROLE_CHANGED_RELOGIN 清态并提示重新登录', async () => {
    const fn = mockAppFetch('REGION');
    await loginAs('REGION');
    await screen.findAllByText('2,767');

    // 后续请求返回 ROLE_CHANGED_RELOGIN（模拟角色被管理端变更）
    fn.mockImplementation(async (url: unknown, init?: RequestInit) => {
      const u = String(url);
      if (u.startsWith('/api/v1/stores') || u.startsWith('/api/v1/kpi')) {
        return jsonRes(errorEnvelope('ROLE_CHANGED_RELOGIN', '角色已变更，请重新登录'), 401);
      }
      return jsonRes(envelope(domainMeta('REGION')));
    });

    // 触发一次刷新：切换筛选 -> 重新拉取 stores/kpi
    await userEvent.click(screen.getByRole('radio', { name: '直营' }));

    expect(await screen.findByText('角色已变更，请重新登录')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument();
  });
});
