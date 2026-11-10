// 会话态：令牌存 sessionStorage（同标签页刷新存活、跨标签页隔离，支持多人并行）。
// 域上下文为内存态（React state），不持久化到 localStorage（design.md §2.3）。

import type { LoginUser } from '../api/types';

const TOKEN_KEY = 'store-ledger-token';

export function saveToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function loadToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export interface Session {
  token: string;
  // 登录快照展示用；域权威上下文以 /me/domain 为准。
  user?: LoginUser;
}
