/**
 * Shared types and interfaces for UI components
 */

export interface Component {
  render(): HTMLElement;
  destroy?(): void;
}

export interface KernelRequestFn {
  (method: string, params: unknown): Promise<unknown>;
}

export class KernelError extends Error {
  code: number;

  constructor(message: string, code: number) {
    super(message);
    this.name = 'KernelError';
    this.code = code;
  }
}

// Helper function for creating DOM elements
export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string> = {}
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    node.setAttribute(k, v);
  }
  return node;
}

// UI component helpers
export function rowHeader(title: string): HTMLDivElement {
  const h = el('div');
  h.textContent = title;
  h.style.fontWeight = '600';
  h.style.marginTop = '12px';
  h.style.marginBottom = '4px';
  return h;
}

export function label(text: string): HTMLDivElement {
  const lbl = el('div');
  lbl.textContent = text;
  lbl.style.fontSize = '12px';
  lbl.style.marginTop = '8px';
  lbl.style.marginBottom = '2px';
  return lbl;
}

export function textInput(value: string): HTMLInputElement {
  const inp = el('input');
  inp.type = 'text';
  inp.value = value;
  inp.style.width = '100%';
  inp.style.padding = '4px';
  inp.style.fontSize = '13px';
  inp.style.border = '1px solid #ccc';
  inp.style.borderRadius = '3px';
  return inp;
}

export function textArea(value: string, heightPx = 90): HTMLTextAreaElement {
  const area = el('textarea');
  area.value = value;
  area.style.width = '100%';
  area.style.minHeight = `${heightPx}px`;
  area.style.padding = '6px';
  area.style.fontSize = '13px';
  area.style.fontFamily = 'monospace';
  area.style.border = '1px solid #ccc';
  area.style.borderRadius = '3px';
  return area;
}

export function smallButton(text: string): HTMLButtonElement {
  const btn = el('button');
  btn.textContent = text;
  btn.style.fontSize = '12px';
  btn.style.padding = '4px 8px';
  return btn;
}
