// 统一 API 客户端：信封解包、Bearer 注入、401 分流、导出双分支（design.md §2.4）。
import type {
  DomainMeta,
  ExportPayload,
  KpiResult,
  LoginResult,
  StoreDetail,
  StoresResult,
} from './types';
import { ERROR_MESSAGES, LedgerApiError } from './errors';

export type QueryValue = string | number | null | undefined;
export type Query = Record<string, QueryValue>;

interface ApiEnvelope {
  data?: unknown;
  error?: { code: string; message?: string } | null;
  trace_id?: string | null;
}

export interface RequestOptions {
  method?: string;
  token?: string | null;
  body?: unknown;
  query?: Query;
}

async function parseError(res: Response): Promise<LedgerApiError> {
  let code = 'INTERNAL_ERROR';
  let message: string = ERROR_MESSAGES.INTERNAL_ERROR;
  let traceId: string | null = null;
  try {
    const payload = await res.json();
    if (payload && payload.error && typeof payload.error.code === 'string') {
      code = payload.error.code;
      message = payload.error.message || ERROR_MESSAGES[code] || ERROR_MESSAGES.INTERNAL_ERROR;
    }
    if (payload && typeof payload.trace_id === 'string') {
      traceId = payload.trace_id;
    }
  } catch {
    // 非 JSON 错误体：保留默认 INTERNAL_ERROR
  }
  return new LedgerApiError(code, message, res.status, traceId);
}

function buildQuery(query?: Query): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.append(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : '';
}

async function requestJson<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`;
  let body: string | undefined;
  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(path + buildQuery(opts.query), {
    method: opts.method ?? 'GET',
    headers,
    body,
  });
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  let payload: unknown;
  try {
    payload = await res.json();
  } catch {
    return undefined as T;
  }
  const env = (payload ?? {}) as ApiEnvelope;
  if (env.error) {
    const code: string = env.error.code;
    const message: string = env.error.message || ERROR_MESSAGES[code] || ERROR_MESSAGES.INTERNAL_ERROR;
    throw new LedgerApiError(code, message, res.status, env.trace_id ?? null);
  }
  return (env.data ?? env) as T;
}

export function login(username: string, password: string): Promise<LoginResult> {
  return requestJson<LoginResult>('/api/v1/auth/login', {
    method: 'POST',
    body: { username, password },
  });
}

export function logout(token: string): Promise<void> {
  return requestJson<void>('/api/v1/auth/logout', { method: 'POST', token });
}

export function getDomain(token: string): Promise<DomainMeta> {
  return requestJson<DomainMeta>('/api/v1/me/domain', { token });
}

export function getStores(token: string, query?: Query): Promise<StoresResult> {
  return requestJson<StoresResult>('/api/v1/stores', { token, query });
}

export function getStoreDetail(token: string, storeId: string): Promise<StoreDetail> {
  return requestJson<StoreDetail>(`/api/v1/stores/${encodeURIComponent(storeId)}`, { token });
}

export function getKpi(token: string, query?: Query): Promise<KpiResult> {
  return requestJson<KpiResult>('/api/v1/kpi', { token, query });
}

export interface ExportResult {
  filename: string;
  rowCount: number;
  signature: string | null;
  blob: Blob;
}

function parseFilename(disposition: string | null): string {
  if (!disposition) return 'store_ledger.csv';
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1].trim());
    } catch {
      return utf8[1].trim();
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain ? plain[1].trim() : 'store_ledger.csv';
}

// 导出是唯一「成功返回非 JSON」的端点：先按 Content-Type 分流，再决定下载或报错。
// 失败（JSON 错误信封）绝不产出文件，也不由本函数构造任何 Blob 下载链接。
export async function exportCsv(token: string, payload: ExportPayload): Promise<ExportResult> {
  const res = await fetch('/api/v1/exports', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('text/csv')) {
    const rowCount = parseInt(res.headers.get('X-Export-Row-Count') || '0', 10);
    const signature = res.headers.get('X-Filter-Signature');
    const blob = await res.blob();
    const filename = parseFilename(res.headers.get('Content-Disposition'));
    return { filename, rowCount, signature, blob };
  }
  throw await parseError(res);
}
