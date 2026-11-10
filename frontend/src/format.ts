// 展示格式化：接口数值直接展示，前端只做千分位/占位，不重算（requirement.md §5 FR-04）。

export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return value.toLocaleString('zh-CN');
}

export function formatMetric(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '—';
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits });
}
