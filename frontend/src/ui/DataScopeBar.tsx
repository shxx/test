// 全局口径条（FR-02）：角色/域标签、数据版本/截止日/YTD（口径由接口下发，不硬编码）。
import type { DomainMeta } from '../api/types';

interface DataScopeBarProps {
  domain: DomainMeta;
  onLogout: () => void;
}

export function DataScopeBar({ domain, onLogout }: DataScopeBarProps) {
  const scopeText = domain.domain.type === 'all' ? '全量' : domain.domain.scope ?? '无域';
  return (
    <header className="scope-bar">
      <div className="scope-bar-left">
        <span className="role-label">
          {domain.role_label}
          {domain.role === 'REGION' && domain.dimensions.region.fixed_value
            ? ` · ${domain.dimensions.region.fixed_value}`
            : domain.role === 'BRAND_BU'
              ? ` · ${domain.domain.scope}`
              : ''}
        </span>
        <span className="scope-meta" aria-label="数据口径">
          数据版本 {domain.data_version} · 截止 {domain.as_of_date} · YTD {domain.ytd.start} ~ {domain.ytd.end}
          {domain.ytd.note ? `（${domain.ytd.note}）` : ''}
        </span>
      </div>
      <div className="scope-bar-right">
        <span className="user-name">{domain.display_name}</span>
        <button type="button" onClick={onLogout}>
          退出登录
        </button>
      </div>
    </header>
  );
}
