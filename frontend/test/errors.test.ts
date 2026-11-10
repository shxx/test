import { describe, expect, it } from 'vitest';
import { isOutOfDomainCode, isSessionExpiredCode, messageFor } from '../src/api/errors';

describe('error code mapping', () => {
  it('maps out-of-domain codes to 超出数据域', () => {
    expect(messageFor('OUT_OF_DOMAIN')).toBe('超出数据域');
    expect(messageFor('EXPORT_OUT_OF_DOMAIN')).toBe('超出数据域');
  });

  it('maps export limit to 请收窄口径', () => {
    expect(messageFor('EXPORT_LIMIT_EXCEEDED')).toBe('请收窄口径');
  });

  it('maps role change to 角色已变更', () => {
    expect(messageFor('ROLE_CHANGED_RELOGIN')).toBe('角色已变更，请重新登录');
  });

  it('unknown code falls back to internal error', () => {
    expect(messageFor('SOMETHING_ELSE')).toBe('服务内部错误');
  });
});

describe('error classification', () => {
  it('isSessionExpiredCode covers all 401 relogin codes except AUTH_FAILED', () => {
    expect(isSessionExpiredCode('TOKEN_MISSING')).toBe(true);
    expect(isSessionExpiredCode('TOKEN_INVALID')).toBe(true);
    expect(isSessionExpiredCode('TOKEN_EXPIRED')).toBe(true);
    expect(isSessionExpiredCode('SESSION_REVOKED')).toBe(true);
    expect(isSessionExpiredCode('ROLE_CHANGED_RELOGIN')).toBe(true);
    expect(isSessionExpiredCode('AUTH_FAILED')).toBe(false);
  });

  it('isOutOfDomainCode covers both 越权 codes', () => {
    expect(isOutOfDomainCode('OUT_OF_DOMAIN')).toBe(true);
    expect(isOutOfDomainCode('EXPORT_OUT_OF_DOMAIN')).toBe(true);
    expect(isOutOfDomainCode('EXPORT_LIMIT_EXCEEDED')).toBe(false);
  });
});
