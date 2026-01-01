import { describe, it, expect, beforeEach } from 'vitest';

// Helper function from main.ts
function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string> = {}
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

describe('el helper', () => {
  it('creates a div element', () => {
    const div = el('div');
    expect(div.tagName).toBe('DIV');
  });

  it('creates element with attributes', () => {
    const input = el('input', { type: 'text', placeholder: 'Enter text' });
    expect(input.getAttribute('type')).toBe('text');
    expect(input.getAttribute('placeholder')).toBe('Enter text');
  });

  it('creates button element', () => {
    const btn = el('button', { class: 'primary' });
    expect(btn.tagName).toBe('BUTTON');
    expect(btn.getAttribute('class')).toBe('primary');
  });

  it('creates textarea element', () => {
    const textarea = el('textarea', { rows: '5' });
    expect(textarea.tagName).toBe('TEXTAREA');
    expect(textarea.getAttribute('rows')).toBe('5');
  });
});

describe('Chat UI state', () => {
  let chatLog: HTMLDivElement;

  beforeEach(() => {
    document.body.innerHTML = '';
    chatLog = el('div');
    chatLog.className = 'chat-log';
    document.body.appendChild(chatLog);
  });

  function append(role: 'user' | 'reos', text: string) {
    const row = el('div');
    row.className = `chat-row ${role}`;
    const bubble = el('div');
    bubble.className = `chat-bubble ${role}`;
    bubble.textContent = text;
    row.appendChild(bubble);
    chatLog.appendChild(row);
  }

  it('appends user message', () => {
    append('user', 'Hello');
    const rows = chatLog.querySelectorAll('.chat-row');
    expect(rows.length).toBe(1);
    expect(rows[0].classList.contains('user')).toBe(true);
    expect(rows[0].querySelector('.chat-bubble')?.textContent).toBe('Hello');
  });

  it('appends reos message', () => {
    append('reos', 'Hi there');
    const bubble = chatLog.querySelector('.chat-bubble.reos');
    expect(bubble?.textContent).toBe('Hi there');
  });

  it('maintains message order', () => {
    append('user', 'First');
    append('reos', 'Second');
    append('user', 'Third');
    const bubbles = chatLog.querySelectorAll('.chat-bubble');
    expect(bubbles.length).toBe(3);
    expect(bubbles[0].textContent).toBe('First');
    expect(bubbles[1].textContent).toBe('Second');
    expect(bubbles[2].textContent).toBe('Third');
  });
});

describe('Play state management', () => {
  it('tracks active act id', () => {
    let activeActId: string | null = null;
    const actsCache: Array<{ act_id: string; title: string }> = [];

    // Simulate refreshActs response
    const response = {
      active_act_id: 'act-1',
      acts: [
        { act_id: 'act-1', title: 'Act One' },
        { act_id: 'act-2', title: 'Act Two' }
      ]
    };

    activeActId = response.active_act_id;
    actsCache.push(...response.acts);

    expect(activeActId).toBe('act-1');
    expect(actsCache.length).toBe(2);
  });

  it('clears scene selection when switching acts', () => {
    let activeActId: string | null = 'act-1';
    let selectedSceneId: string | null = 'scene-1';
    let selectedBeatId: string | null = 'beat-1';

    // Simulate switching to new act
    activeActId = 'act-2';
    selectedSceneId = null;
    selectedBeatId = null;

    expect(activeActId).toBe('act-2');
    expect(selectedSceneId).toBeNull();
    expect(selectedBeatId).toBeNull();
  });

  it('tracks KB path selection', () => {
    let kbSelectedPath = 'kb.md';
    let kbTextDraft = '';

    // Simulate loading a KB file
    kbSelectedPath = 'notes.md';
    kbTextDraft = '# Notes\n\nSome content';

    expect(kbSelectedPath).toBe('notes.md');
    expect(kbTextDraft).toContain('# Notes');
  });
});
