// 错误码 -> 前端提示（requirement.md §7.2 / design.md §1.4）。
// 前端只映射 error.code，不展示堆栈/SQL/凭据。

export const ERROR_MESSAGES: Record<string, string> = {
  AUTH_FAILED: '账号或口令错误',
  TOKEN_MISSING: '会话已失效，请重新登录',
  TOKEN_INVALID: '会话已失效，请重新登录',
  TOKEN_EXPIRED: '会话已失效，请重新登录',
  SESSION_REVOKED: '会话已失效，请重新登录',
  ROLE_CHANGED_RELOGIN: '角色已变更，请重新登录',
  NO_VALID_DOMAIN: '无有效数据域',
  OUT_OF_DOMAIN: '超出数据域',
  EXPORT_OUT_OF_DOMAIN: '超出数据域',
  EXPORT_LIMIT_EXCEEDED: '请收窄口径',
  EXPORT_DISABLED: '导出已禁用',
  INVALID_FILTER: '筛选条件不合法',
  LOCKED_DIMENSION: '已锁定',
  ADMIN_FORBIDDEN: '无权限',
  NOT_FOUND: '资源不存在',
  METHOD_NOT_ALLOWED: '方法不允许',
  INTERNAL_ERROR: '服务内部错误',
};

export function messageFor(code: string): string {
  return ERROR_MESSAGES[code] ?? '服务内部错误';
}

export class LedgerApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly traceId: string | null;

  constructor(code: string, message: string, status: number, traceId: string | null) {
    super(message);
    this.name = 'LedgerApiError';
    this.code = code;
    this.status = status;
    this.traceId = traceId;
  }
}

// 401 中除登录失败外，均需清理会话态并跳回登录页。
export function isSessionExpiredCode(code: string): boolean {
  return (
    code === 'TOKEN_MISSING' ||
    code === 'TOKEN_INVALID' ||
    code === 'TOKEN_EXPIRED' ||
    code === 'SESSION_REVOKED' ||
    code === 'ROLE_CHANGED_RELOGIN'
  );
}

// 越权（详情 / 导出整单拒绝）统一提示「超出数据域」。
export function isOutOfDomainCode(code: string): boolean {
  return code === 'OUT_OF_DOMAIN' || code === 'EXPORT_OUT_OF_DOMAIN';
}
