// 登录页（FR-01 / AC-08）：账号/口令登录，AUTH_FAILED 表单内提示并清空口令。
import { useState, type FormEvent } from 'react';
import { login } from '../api/client';
import { LedgerApiError, messageFor } from '../api/errors';
import type { LoginUser } from '../api/types';

interface LoginProps {
  notice?: string | null;
  onLogin: (token: string, user: LoginUser) => void;
}

export function Login({ notice, onLogin }: LoginProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await login(username, password);
      onLogin(result.token, result.user);
    } catch (err) {
      if (err instanceof LedgerApiError) {
        setError(messageFor(err.code));
        if (err.code === 'AUTH_FAILED') setPassword('');
      } else {
        setError('登录失败，请稍后重试');
      }
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={handleSubmit} aria-labelledby="login-title">
        <h1 id="login-title">门店网络台账管理后台</h1>
        {notice ? (
          <p className="login-notice" role="alert">
            {notice}
          </p>
        ) : null}
        <div className="field">
          <label htmlFor="username">账号</label>
          <input
            id="username"
            name="username"
            type="text"
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="password">口令</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error ? (
          <p className="login-error" role="alert">
            {error}
          </p>
        ) : null}
        <button type="submit" disabled={submitting}>
          {submitting ? '登录中…' : '登录'}
        </button>
      </form>
    </main>
  );
}
