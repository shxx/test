// 应用根：登录 -> 域握手 -> 主界面；401/角色变更统一清态跳登录（FR-01/FR-02/AC-08）。
import { useCallback, useEffect, useState } from 'react';
import { getDomain, logout } from './api/client';
import { isSessionExpiredCode, LedgerApiError, messageFor } from './api/errors';
import type { DomainMeta, LoginUser } from './api/types';
import { resetCoordCache } from './coord/gcj02bd09';
import { clearToken, loadToken, saveToken, type Session } from './state/session';
import { FilterProvider, useFilter } from './state/FilterContext';
import { useLedgerData } from './state/useLedgerData';
import { Login } from './ui/Login';
import { DataScopeBar } from './ui/DataScopeBar';
import { FilterAccordion } from './ui/FilterAccordion';
import { MapPanel } from './ui/MapPanel';
import { SummaryCard } from './ui/SummaryCard';
import { KpiCards } from './ui/KpiCards';
import { LedgerTable } from './ui/LedgerTable';
import { ExportButton } from './ui/ExportButton';
import { StoreDrawer } from './ui/StoreDrawer';

export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [domain, setDomain] = useState<DomainMeta | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [booting, setBooting] = useState(true);

  // 恢复令牌（sessionStorage）：刷新后同标签页保持登录，跨标签页隔离。
  useEffect(() => {
    const token = loadToken();
    if (token) setSession({ token });
    else setBooting(false);
  }, []);

  const handleSessionError = useCallback((err: LedgerApiError) => {
    if (isSessionExpiredCode(err.code) || err.code === 'NO_VALID_DOMAIN') {
      clearToken();
      resetCoordCache();
      setSession(null);
      setDomain(null);
      setNotice(messageFor(err.code));
    }
  }, []);

  // 域元数据握手：登录成功后先握手再渲染主界面（避免越域/全国视野闪烁）。
  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    setBooting(true);
    getDomain(session.token)
      .then((d) => {
        if (cancelled) return;
        setDomain(d);
        setBooting(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setBooting(false);
        if (err instanceof LedgerApiError) handleSessionError(err);
      });
    return () => {
      cancelled = true;
    };
  }, [session, handleSessionError]);

  function handleLogin(token: string, user: LoginUser) {
    saveToken(token);
    setSession({ token, user });
    setNotice(null);
  }

  function handleLogout() {
    const token = session?.token;
    if (token) {
      logout(token).catch(() => {
        /* 尽力而为：登出失败仍清本地态 */
      });
    }
    clearToken();
    resetCoordCache();
    setSession(null);
    setDomain(null);
    setNotice(null);
  }

  if (session && domain) {
    return (
      <MainInterface
        token={session.token}
        domain={domain}
        onLogout={handleLogout}
        onSessionError={handleSessionError}
      />
    );
  }

  if (session && !domain && booting) {
    return (
      <main className="loading-page" aria-live="polite">
        正在加载数据域…
      </main>
    );
  }

  return <Login notice={notice} onLogin={handleLogin} />;
}

interface MainInterfaceProps {
  token: string;
  domain: DomainMeta;
  onLogout: () => void;
  onSessionError: (err: LedgerApiError) => void;
}

function MainInterface({ token, domain, onLogout, onSessionError }: MainInterfaceProps) {
  return (
    <FilterProvider>
      <MainBody token={token} domain={domain} onLogout={onLogout} onSessionError={onSessionError} />
    </FilterProvider>
  );
}

function MainBody({ token, domain, onLogout, onSessionError }: Omit<MainInterfaceProps, 'token'> & { token: string }) {
  const { state, dispatch } = useFilter();
  const data = useLedgerData(token, state, onSessionError);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedCount, setSelectedCount] = useState<number | null>(null);

  const openDetail = useCallback((id: string) => setSelectedId(id), []);
  const closeDetail = useCallback(() => setSelectedId(null), []);

  // Esc 取消当前选择（无抽屉打开时清省份/城市，等价地图 Esc 取消）。
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== 'Escape' || selectedId) return;
      if (state.province || state.city) {
        dispatch({ type: 'set', key: 'province', value: null });
        dispatch({ type: 'set', key: 'city', value: null });
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [selectedId, state.province, state.city, dispatch]);

  return (
    <div className="app-shell">
      <DataScopeBar domain={domain} onLogout={onLogout} />
      {!data.signaturesConsistent ? (
        <p className="consistency-warning" role="alert">
          各视图口径签名不一致，已暂停渲染以提示排查（filter_signature 不一致）。
        </p>
      ) : null}
      {data.error && !isSessionExpiredCode(data.error.code) && data.error.code !== 'NO_VALID_DOMAIN' ? (
        <p className="consistency-warning" role="alert">
          {messageFor(data.error.code)}
        </p>
      ) : null}
      <div className="layout">
        <FilterAccordion domain={domain} />
        <main className="main-col">
          <MapPanel
            token={token}
            domain={domain}
            kpi={data.kpi}
            onOpenDetail={openDetail}
            onSessionError={onSessionError}
            onSelectedCountChange={setSelectedCount}
          />
          <SummaryCard kpi={data.kpi} loading={data.loading} selectedCount={selectedCount} />
          <KpiCards kpi={data.kpi} loading={data.loading} />
          <ExportButton token={token} onSessionError={onSessionError} />
          <LedgerTable stores={data.stores} loading={data.loading} onOpenDetail={openDetail} />
        </main>
      </div>
      {selectedId ? (
        <StoreDrawer
          token={token}
          storeId={selectedId}
          onClose={closeDetail}
          onSessionError={onSessionError}
        />
      ) : null}
    </div>
  );
}
