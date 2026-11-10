// 焦点陷阱（抽屉 modal）：Tab 循环在容器内，Esc 由调用方处理（design.md §5.1）。
export function trapFocus(container: HTMLElement, event: KeyboardEvent): void {
  if (event.key !== 'Tab') return;
  const focusables = Array.from(
    container.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((el) => !el.hasAttribute('disabled') && el.getAttribute('aria-hidden') !== 'true');
  if (focusables.length === 0) return;
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  const active = document.activeElement as Node | null;
  if (event.shiftKey) {
    if (active === first || !container.contains(active)) {
      event.preventDefault();
      last.focus();
    }
  } else if (active === last || !container.contains(active)) {
    event.preventDefault();
    first.focus();
  }
}

export function getFocusable(container: HTMLElement): HTMLElement | null {
  const el = container.querySelector<HTMLElement>(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
  );
  return el ?? null;
}
