import { afterEach, describe, expect, it, vi } from 'vitest';
import { exportCsv, getDomain, login } from '../src/api/client';
import { LedgerApiError } from '../src/api/errors';
import { csvRes, domainMeta, jsonRes, loginResult } from './fixtures';

function envelope(data: unknown) {
  return { data, meta: { data_version: '2026YTD08', as_of_date: '2026-08-31' }, error: null, trace_id: 't1' };
}

function errorEnvelope(code: string, message: string) {
  return { data: null, meta: {}, error: { code, message }, trace_id: 't1' };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('login', () => {
  it('returns the login result on success', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes(envelope(loginResult('HQ'))));
    vi.stubGlobal('fetch', fetchMock);

    const result = await login('hq', 'Demo@12345');
    expect(result.token).toBe('token-HQ');
    expect(result.user.role).toBe('HQ');
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/login', expect.objectContaining({ method: 'POST' }));
  });

  it('throws LedgerApiError(AUTH_FAILED) on 401', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonRes(errorEnvelope('AUTH_FAILED', '账号或口令错误'), 401)));
    await expect(login('hq', 'wrong')).rejects.toMatchObject({ code: 'AUTH_FAILED', status: 401 });
  });
});

describe('getDomain', () => {
  it('injects Bearer token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonRes(envelope(domainMeta('HQ'))));
    vi.stubGlobal('fetch', fetchMock);
    const d = await getDomain('tok');
    expect(d.role).toBe('HQ');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/me/domain',
      expect.objectContaining({ headers: { Authorization: 'Bearer tok' } }),
    );
  });

  it('surfaces ROLE_CHANGED_RELOGIN', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonRes(errorEnvelope('ROLE_CHANGED_RELOGIN', '角色已变更，请重新登录'), 401)));
    await expect(getDomain('tok')).rejects.toMatchObject({ code: 'ROLE_CHANGED_RELOGIN' });
  });
});

describe('exportCsv (dual-branch)', () => {
  it('success: text/csv -> returns blob + row count + filename', async () => {
    const csv = '\ufeff# 水印\r\nstore_id\r\nS1\r\n';
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        csvRes(csv, {
          'X-Export-Row-Count': '5000',
          'X-Filter-Signature': 'sig-x',
          'Content-Disposition': "attachment; filename=\"store_ledger.csv\"; filename*=UTF-8''%E9%97%A8%E5%BA%97.csv",
        }),
      ),
    );
    const result = await exportCsv('tok', { filters: { province: '上海' } });
    expect(result.rowCount).toBe(5000);
    expect(result.signature).toBe('sig-x');
    expect(result.filename).toContain('门店');
    expect(result.blob).toBeInstanceOf(Blob);
  });

  it('error: JSON envelope -> throws and produces no CSV metadata', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonRes(errorEnvelope('EXPORT_LIMIT_EXCEEDED', '请收窄口径'), 422)),
    );
    await expect(exportCsv('tok', { filters: {} })).rejects.toMatchObject({
      code: 'EXPORT_LIMIT_EXCEEDED',
      status: 422,
    });
  });

  it('error: EXPORT_OUT_OF_DOMAIN -> 超出数据域', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonRes(errorEnvelope('EXPORT_OUT_OF_DOMAIN', '超出数据域（拒绝整单）'), 403)));
    const err = await exportCsv('tok', { store_ids: ['S_OUT'] }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(LedgerApiError);
    expect((err as LedgerApiError).code).toBe('EXPORT_OUT_OF_DOMAIN');
  });
});
