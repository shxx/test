// 左栏筛选手风琴（FR-07 / AC-05/09）：
// 省份/城市/区块/经营方式为可编辑维度；大区仅 REGION 锁定只读（dimensions 驱动，D-12）。
import { useState, type ReactNode } from 'react';
import type { DomainMeta } from '../api/types';
import { useFilter } from '../state/FilterContext';
import type { EditableFilterKey } from '../state/filters';

interface FilterAccordionProps {
  domain: DomainMeta;
}

interface SectionProps {
  id: string;
  title: ReactNode;
  children: ReactNode;
}

function Section({ id, title, children }: SectionProps) {
  const [open, setOpen] = useState(true);
  const bodyId = `${id}-body`;
  return (
    <div className="accordion-section">
      <button
        type="button"
        className="accordion-header"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((v) => !v)}
      >
        <span>{title}</span>
        <span aria-hidden="true">{open ? '−' : '+'}</span>
      </button>
      <div id={bodyId} className="accordion-body" hidden={!open}>
        {children}
      </div>
    </div>
  );
}

function RadioList({
  name,
  options,
  value,
  onChange,
  allowAllLabel = '全部',
}: {
  name: string;
  options: string[];
  value: string | null;
  onChange: (value: string | null) => void;
  allowAllLabel?: string;
}) {
  return (
    <div className="radio-list" role="group">
      <label className="radio-item">
        <input
          type="radio"
          name={name}
          checked={value === null}
          onChange={() => onChange(null)}
        />
        <span>{allowAllLabel}</span>
      </label>
      {options.map((opt) => (
        <label className="radio-item" key={opt}>
          <input
            type="radio"
            name={name}
            value={opt}
            checked={value === opt}
            onChange={() => onChange(opt)}
          />
          <span>{opt}</span>
        </label>
      ))}
    </div>
  );
}

const OPERATE_TYPES = ['直营', '加盟'];

export function FilterAccordion({ domain }: FilterAccordionProps) {
  const { state, dispatch } = useFilter();

  function setFilter(key: EditableFilterKey, value: string | null) {
    dispatch({ type: 'set', key, value });
  }

  const regionLocked = domain.dimensions.region.locked;

  return (
    <aside className="filter-panel" aria-label="筛选条件">
      <h2 className="filter-title">筛选</h2>

      <Section id="filter-province" title="省份">
        <RadioList
          name="filter-province"
          options={domain.provinces}
          value={state.province}
          onChange={(v) => setFilter('province', v)}
        />
      </Section>

      <Section id="filter-city" title="城市">
        <label className="select-label" htmlFor="filter-city-select">
          城市
        </label>
        <select
          id="filter-city-select"
          value={state.city ?? ''}
          onChange={(e) => setFilter('city', e.target.value || null)}
        >
          <option value="">全部</option>
          {domain.cities.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </Section>

      <Section id="filter-block" title="区块">
        <label className="select-label" htmlFor="filter-block-select">
          区块
        </label>
        <select
          id="filter-block-select"
          value={state.block ?? ''}
          onChange={(e) => setFilter('block', e.target.value || null)}
        >
          <option value="">全部</option>
          {domain.blocks.map((b) => (
            <option key={b} value={b}>
              {b}
            </option>
          ))}
        </select>
      </Section>

      <Section id="filter-operate" title="经营方式">
        <RadioList
          name="filter-operate"
          options={OPERATE_TYPES}
          value={state.operate_type}
          onChange={(v) => setFilter('operate_type', v)}
        />
      </Section>

      {regionLocked ? (
        <Section id="filter-region" title="大区">
          <div className="locked-dimension" role="group" aria-label="大区（已锁定）">
            <span className="locked-value">{domain.dimensions.region.fixed_value ?? '—'}</span>
            <span className="badge badge-locked">已锁定</span>
          </div>
        </Section>
      ) : null}
    </aside>
  );
}
