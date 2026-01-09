/**
 * CAIRN View - Conversational interface for the Attention Minder.
 *
 * CAIRN surfaces what needs attention without being coercive:
 * - Priority-driven surfacing
 * - Calendar and time awareness
 * - Knowledge base queries
 * - Gentle nudges, never guilt-trips
 */

import { el } from './dom';
import type { ChatRespondResult } from './types';

interface CairnViewCallbacks {
  onSendMessage: (message: string) => Promise<void>;
  kernelRequest: (method: string, params: unknown) => Promise<unknown>;
}

/** Full message data including LLM context for expandable details */
interface MessageData {
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  // Assistant-only fields from ChatRespondResult
  thinkingSteps?: string[];
  toolCalls?: Array<{
    name: string;
    arguments: Record<string, unknown>;
    ok: boolean;
    result?: unknown;
    error?: { code: string; message: string; data?: unknown };
  }>;
  messageId?: string;
  messageType?: string;
}

interface CairnViewState {
  chatMessages: MessageData[];
  surfacedItems: Array<{ title: string; reason: string; urgency: string }>;
}

/**
 * Creates the CAIRN conversational view.
 */
export function createCairnView(
  callbacks: CairnViewCallbacks
): {
  container: HTMLElement;
  addChatMessage: (role: 'user' | 'assistant', content: string) => void;
  addAssistantMessage: (result: ChatRespondResult) => void;
  showThinking: () => void;
  hideThinking: () => void;
  clearChat: () => void;
  getChatInput: () => HTMLInputElement;
  updateSurfaced: (items: Array<{ title: string; reason: string; urgency: string }>) => void;
} {
  const state: CairnViewState = {
    chatMessages: [],
    surfacedItems: [],
  };

  // Main container
  const container = el('div');
  container.className = 'cairn-view';
  container.style.cssText = `
    display: flex;
    flex: 1;
    height: 100%;
    overflow: hidden;
  `;

  // ============ LEFT: Surfaced Items Panel ============
  const surfacedPanel = el('div');
  surfacedPanel.className = 'surfaced-panel';
  surfacedPanel.style.cssText = `
    width: 320px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-right: 1px solid rgba(255,255,255,0.1);
    background: rgba(0,0,0,0.1);
  `;

  // Surfaced header
  const surfacedHeader = el('div');
  surfacedHeader.style.cssText = `
    padding: 16px 20px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    background: rgba(0,0,0,0.2);
  `;

  const surfacedTitle = el('div');
  surfacedTitle.style.cssText = `
    font-size: 16px;
    font-weight: 600;
    color: #fff;
    display: flex;
    align-items: center;
    gap: 8px;
  `;
  surfacedTitle.innerHTML = '🪨 What Needs Attention';

  const surfacedSubtitle = el('div');
  surfacedSubtitle.style.cssText = `
    font-size: 12px;
    color: rgba(255,255,255,0.5);
    margin-top: 4px;
  `;
  surfacedSubtitle.textContent = 'Surfaced by priority and time';

  surfacedHeader.appendChild(surfacedTitle);
  surfacedHeader.appendChild(surfacedSubtitle);

  // Surfaced items list
  const surfacedList = el('div');
  surfacedList.className = 'surfaced-list';
  surfacedList.style.cssText = `
    flex: 1;
    overflow-y: auto;
    padding: 12px;
  `;

  // Quick actions
  const quickActions = el('div');
  quickActions.style.cssText = `
    padding: 12px;
    border-top: 1px solid rgba(255,255,255,0.1);
    display: flex;
    flex-direction: column;
    gap: 8px;
  `;

  const actionButtons = [
    { label: "What's next?", icon: '🎯', action: "What should I focus on next?" },
    { label: "Today's plan", icon: '📅', action: "What's on my calendar today?" },
    { label: 'Waiting on', icon: '⏳', action: "What am I waiting on?" },
    { label: 'Stale items', icon: '📦', action: "What have I been neglecting?" },
  ];

  actionButtons.forEach(({ label, icon, action }) => {
    const btn = el('button');
    btn.innerHTML = `${icon} ${label}`;
    btn.style.cssText = `
      padding: 10px 12px;
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 6px;
      color: rgba(255,255,255,0.8);
      cursor: pointer;
      font-size: 12px;
      text-align: left;
      transition: background 0.2s;
    `;
    btn.addEventListener('mouseenter', () => {
      btn.style.background = 'rgba(255,255,255,0.1)';
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.background = 'rgba(255,255,255,0.05)';
    });
    btn.addEventListener('click', () => {
      callbacks.onSendMessage(action);
    });
    quickActions.appendChild(btn);
  });

  surfacedPanel.appendChild(surfacedHeader);
  surfacedPanel.appendChild(surfacedList);
  surfacedPanel.appendChild(quickActions);

  // ============ RIGHT: Chat Panel ============
  const chatPanel = el('div');
  chatPanel.className = 'chat-panel';
  chatPanel.style.cssText = `
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  `;

  // Chat header
  const chatHeader = el('div');
  chatHeader.style.cssText = `
    padding: 16px 20px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    background: rgba(0,0,0,0.2);
  `;

  const chatTitle = el('div');
  chatTitle.style.cssText = `
    font-size: 16px;
    font-weight: 600;
    color: #fff;
  `;
  chatTitle.textContent = 'CAIRN';

  const chatSubtitle = el('div');
  chatSubtitle.style.cssText = `
    font-size: 12px;
    color: rgba(255,255,255,0.5);
    margin-top: 4px;
  `;
  chatSubtitle.textContent = 'Your attention minder';

  chatHeader.appendChild(chatTitle);
  chatHeader.appendChild(chatSubtitle);

  // Chat messages area
  const chatMessages = el('div');
  chatMessages.className = 'chat-messages';
  chatMessages.style.cssText = `
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  `;

  // Welcome message
  const welcomeMsg = el('div');
  welcomeMsg.style.cssText = `
    background: rgba(59, 130, 246, 0.1);
    border: 1px solid rgba(59, 130, 246, 0.2);
    border-radius: 12px;
    padding: 16px;
    color: rgba(255,255,255,0.9);
  `;
  welcomeMsg.innerHTML = `
    <div style="font-weight: 600; margin-bottom: 8px;">Welcome to CAIRN</div>
    <div style="font-size: 13px; line-height: 1.5; color: rgba(255,255,255,0.7);">
      I help you stay on top of what matters. Ask me about your priorities,
      what needs attention, or what you should focus on next.
    </div>
  `;
  chatMessages.appendChild(welcomeMsg);

  // Thunderbird integration prompt (shown if not connected and not declined)
  const thunderbirdPrompt = el('div');
  thunderbirdPrompt.style.cssText = `
    background: rgba(59, 130, 246, 0.1);
    border: 1px solid rgba(59, 130, 246, 0.3);
    border-radius: 12px;
    padding: 16px;
    color: rgba(255,255,255,0.9);
    display: none;
  `;
  chatMessages.appendChild(thunderbirdPrompt);

  // Interface for Thunderbird check result
  interface ThunderbirdCheckResult {
    installed: boolean;
    install_suggestion: string | null;
    profiles: Array<{ name: string; accounts: Array<{ email: string }> }>;
    integration_state: 'not_configured' | 'active' | 'declined';
    active_profiles: string[];
  }

  // Update Thunderbird prompt content based on state
  function updateThunderbirdPrompt(status: ThunderbirdCheckResult) {
    // Don't show if declined or active
    if (status.integration_state === 'declined' || status.integration_state === 'active') {
      thunderbirdPrompt.style.display = 'none';
      return;
    }

    const profileCount = status.profiles.length;
    const accountCount = status.profiles.reduce((sum, p) => sum + p.accounts.length, 0);

    if (!status.installed) {
      // Not installed - show install guide
      thunderbirdPrompt.style.background = 'rgba(245, 158, 11, 0.1)';
      thunderbirdPrompt.style.borderColor = 'rgba(245, 158, 11, 0.3)';
      thunderbirdPrompt.innerHTML = `
        <div style="display: flex; align-items: flex-start; gap: 12px;">
          <span style="font-size: 24px;">📅</span>
          <div style="flex: 1;">
            <div style="font-weight: 600; margin-bottom: 6px; color: #f59e0b;">Connect Your Calendar & Contacts</div>
            <div style="font-size: 13px; line-height: 1.5; color: rgba(255,255,255,0.7); margin-bottom: 12px;">
              Thunderbird isn't installed yet. I can help you track appointments and know who you're working with.
            </div>
            <div style="font-size: 12px; color: rgba(255,255,255,0.5); margin-bottom: 12px; font-family: monospace; background: rgba(0,0,0,0.2); padding: 8px; border-radius: 4px;">
              ${status.install_suggestion || 'Install Thunderbird from your package manager'}
            </div>
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
              <button class="tb-dismiss" style="padding: 8px 16px; background: rgba(255,255,255,0.1); border: none; border-radius: 6px; color: rgba(255,255,255,0.7); cursor: pointer; font-size: 12px;">Not now</button>
              <button class="tb-never" style="padding: 8px 16px; background: none; border: none; color: rgba(255,255,255,0.4); cursor: pointer; font-size: 12px;">Never ask again</button>
            </div>
          </div>
        </div>
      `;
    } else {
      // Installed but not configured
      thunderbirdPrompt.style.background = 'rgba(59, 130, 246, 0.1)';
      thunderbirdPrompt.style.borderColor = 'rgba(59, 130, 246, 0.3)';
      thunderbirdPrompt.innerHTML = `
        <div style="display: flex; align-items: flex-start; gap: 12px;">
          <span style="font-size: 24px;">📅</span>
          <div style="flex: 1;">
            <div style="font-weight: 600; margin-bottom: 6px; color: #3b82f6;">Connect Your Calendar & Contacts</div>
            <div style="font-size: 13px; line-height: 1.5; color: rgba(255,255,255,0.7); margin-bottom: 12px;">
              ${profileCount > 0
                ? `Found ${profileCount} profile${profileCount > 1 ? 's' : ''} with ${accountCount} account${accountCount > 1 ? 's' : ''}. Connect to enable time-aware surfacing.`
                : 'Connect Thunderbird to help me track your calendar and contacts.'}
            </div>
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
              <button class="tb-connect" style="padding: 8px 16px; background: #3b82f6; border: none; border-radius: 6px; color: #fff; cursor: pointer; font-size: 12px; font-weight: 500;">Connect${profileCount > 0 ? ' All' : ''}</button>
              <button class="tb-dismiss" style="padding: 8px 16px; background: rgba(255,255,255,0.1); border: none; border-radius: 6px; color: rgba(255,255,255,0.7); cursor: pointer; font-size: 12px;">Not now</button>
              <button class="tb-never" style="padding: 8px 16px; background: none; border: none; color: rgba(255,255,255,0.4); cursor: pointer; font-size: 12px;">Never ask again</button>
            </div>
          </div>
        </div>
      `;
    }

    // Add event listeners
    const connectBtn = thunderbirdPrompt.querySelector('.tb-connect');
    const dismissBtn = thunderbirdPrompt.querySelector('.tb-dismiss');
    const neverBtn = thunderbirdPrompt.querySelector('.tb-never');

    if (connectBtn) {
      connectBtn.addEventListener('click', async () => {
        try {
          const profileNames = status.profiles.map(p => p.name);
          await callbacks.kernelRequest('thunderbird/configure', {
            active_profiles: profileNames,
            all_active: true,
          });
          thunderbirdPrompt.style.display = 'none';
        } catch (e) {
          console.error('Failed to connect Thunderbird:', e);
        }
      });
    }

    if (dismissBtn) {
      dismissBtn.addEventListener('click', () => {
        thunderbirdPrompt.style.display = 'none';
      });
    }

    if (neverBtn) {
      neverBtn.addEventListener('click', async () => {
        try {
          await callbacks.kernelRequest('thunderbird/decline', {});
          thunderbirdPrompt.style.display = 'none';
        } catch (e) {
          console.error('Failed to decline Thunderbird:', e);
        }
      });
    }

    thunderbirdPrompt.style.display = 'block';
  }

  // Check Thunderbird status on load
  void (async () => {
    try {
      const status = await callbacks.kernelRequest('thunderbird/check', {}) as ThunderbirdCheckResult;
      updateThunderbirdPrompt(status);
    } catch (e) {
      // Fall back to old status check
      try {
        const oldStatus = await callbacks.kernelRequest('cairn/thunderbird/status', {}) as { available: boolean };
        if (!oldStatus.available) {
          // Show simple prompt for backwards compatibility
          thunderbirdPrompt.innerHTML = `
            <div style="display: flex; align-items: flex-start; gap: 12px;">
              <span style="font-size: 24px;">📧</span>
              <div style="flex: 1;">
                <div style="font-weight: 600; margin-bottom: 6px; color: #f59e0b;">Connect Thunderbird?</div>
                <div style="font-size: 13px; line-height: 1.5; color: rgba(255,255,255,0.7);">
                  CAIRN can integrate with Thunderbird to help manage your calendar events and contacts.
                </div>
              </div>
            </div>
          `;
          thunderbirdPrompt.style.display = 'block';
        }
      } catch {
        console.log('Thunderbird status check failed:', e);
      }
    }
  })();

  // Thinking indicator (animated dots)
  const thinkingIndicator = el('div');
  thinkingIndicator.className = 'thinking-indicator';
  thinkingIndicator.style.cssText = `
    display: none;
    align-self: flex-start;
    background: rgba(255,255,255,0.1);
    border-radius: 12px;
    padding: 12px 16px;
    margin-top: 8px;
  `;
  thinkingIndicator.innerHTML = `
    <div style="display: flex; align-items: center; gap: 8px;">
      <div class="thinking-dots" style="display: flex; gap: 4px;">
        <span class="dot" style="width: 8px; height: 8px; border-radius: 50%; background: rgba(255,255,255,0.6); animation: pulse 1.4s ease-in-out infinite;"></span>
        <span class="dot" style="width: 8px; height: 8px; border-radius: 50%; background: rgba(255,255,255,0.6); animation: pulse 1.4s ease-in-out 0.2s infinite;"></span>
        <span class="dot" style="width: 8px; height: 8px; border-radius: 50%; background: rgba(255,255,255,0.6); animation: pulse 1.4s ease-in-out 0.4s infinite;"></span>
      </div>
      <span style="color: rgba(255,255,255,0.5); font-size: 13px;">Thinking...</span>
    </div>
  `;
  // Add CSS animation via style tag
  const styleTag = document.createElement('style');
  styleTag.textContent = `
    @keyframes pulse {
      0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
      40% { opacity: 1; transform: scale(1); }
    }
  `;
  document.head.appendChild(styleTag);
  chatMessages.appendChild(thinkingIndicator);

  // Chat input area
  const inputArea = el('div');
  inputArea.style.cssText = `
    padding: 16px;
    border-top: 1px solid rgba(255,255,255,0.1);
    background: rgba(0,0,0,0.1);
  `;

  const inputRow = el('div');
  inputRow.style.cssText = `
    display: flex;
    gap: 8px;
  `;

  const chatInput = el('input') as HTMLInputElement;
  chatInput.type = 'text';
  chatInput.placeholder = 'Ask CAIRN anything...';
  chatInput.style.cssText = `
    flex: 1;
    padding: 12px 16px;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    color: #fff;
    font-size: 14px;
    outline: none;
  `;

  const sendBtn = el('button');
  sendBtn.textContent = 'Send';
  sendBtn.style.cssText = `
    padding: 12px 20px;
    background: #3b82f6;
    border: none;
    border-radius: 8px;
    color: #fff;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.2s;
  `;

  const handleSend = async () => {
    const message = chatInput.value.trim();
    if (!message) return;

    chatInput.value = '';
    addChatMessage('user', message);
    await callbacks.onSendMessage(message);
  };

  chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleSend();
  });
  sendBtn.addEventListener('click', handleSend);

  inputRow.appendChild(chatInput);
  inputRow.appendChild(sendBtn);
  inputArea.appendChild(inputRow);

  chatPanel.appendChild(chatHeader);
  chatPanel.appendChild(chatMessages);
  chatPanel.appendChild(inputArea);

  // Assemble container
  container.appendChild(surfacedPanel);
  container.appendChild(chatPanel);

  // ============ Functions ============

  function renderChatMessage(data: MessageData): HTMLElement {
    const { role, content, thinkingSteps, toolCalls } = data;
    const hasDetails = role === 'assistant' && ((thinkingSteps && thinkingSteps.length > 0) || (toolCalls && toolCalls.length > 0));

    const msgWrapper = el('div');
    msgWrapper.style.cssText = `
      max-width: 85%;
      ${role === 'user' ? 'align-self: flex-end; margin-left: auto;' : 'align-self: flex-start;'}
    `;

    // Main message bubble
    const msgEl = el('div');
    msgEl.style.cssText = `
      padding: 12px 16px;
      border-radius: 12px;
      font-size: 14px;
      line-height: 1.5;
      ${role === 'user'
        ? 'background: #3b82f6; color: #fff;'
        : 'background: rgba(255,255,255,0.1); color: rgba(255,255,255,0.9);'
      }
    `;
    msgEl.textContent = content;
    msgWrapper.appendChild(msgEl);

    // Expandable details for assistant messages
    if (hasDetails) {
      const detailsToggle = el('button');
      detailsToggle.textContent = 'Show details';
      detailsToggle.style.cssText = `
        background: none;
        border: none;
        color: rgba(255,255,255,0.4);
        font-size: 11px;
        padding: 4px 0;
        cursor: pointer;
        margin-top: 4px;
      `;

      const detailsPanel = el('div');
      detailsPanel.style.cssText = `
        display: none;
        margin-top: 8px;
        padding: 12px;
        background: rgba(0,0,0,0.3);
        border-radius: 8px;
        font-size: 12px;
        max-height: 300px;
        overflow-y: auto;
      `;

      // Build details content
      let detailsHTML = '';

      if (thinkingSteps && thinkingSteps.length > 0) {
        detailsHTML += `
          <div style="margin-bottom: 12px;">
            <div style="color: #60a5fa; font-weight: 600; margin-bottom: 6px;">Thinking Steps</div>
            <div style="color: rgba(255,255,255,0.7); white-space: pre-wrap; font-family: monospace; font-size: 11px;">
              ${thinkingSteps.map((step, i) => `${i + 1}. ${escapeHtml(step)}`).join('\n')}
            </div>
          </div>
        `;
      }

      if (toolCalls && toolCalls.length > 0) {
        detailsHTML += `
          <div>
            <div style="color: #60a5fa; font-weight: 600; margin-bottom: 6px;">Tool Calls</div>
            ${toolCalls.map(tc => `
              <div style="margin-bottom: 8px; padding: 8px; background: rgba(255,255,255,0.05); border-radius: 4px;">
                <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
                  <span style="color: #f59e0b; font-weight: 500;">${escapeHtml(tc.name)}</span>
                  <span style="font-size: 10px; padding: 2px 6px; border-radius: 4px; ${tc.ok ? 'background: rgba(34,197,94,0.2); color: #22c55e;' : 'background: rgba(239,68,68,0.2); color: #ef4444;'}">${tc.ok ? 'OK' : 'ERROR'}</span>
                </div>
                <div style="color: rgba(255,255,255,0.5); font-family: monospace; font-size: 10px; word-break: break-all;">
                  Args: ${escapeHtml(JSON.stringify(tc.arguments, null, 2).substring(0, 200))}${JSON.stringify(tc.arguments).length > 200 ? '...' : ''}
                </div>
                ${tc.error ? `<div style="color: #ef4444; margin-top: 4px;">Error: ${escapeHtml(tc.error.message)}</div>` : ''}
              </div>
            `).join('')}
          </div>
        `;
      }

      detailsPanel.innerHTML = detailsHTML;

      let expanded = false;
      detailsToggle.addEventListener('click', () => {
        expanded = !expanded;
        detailsPanel.style.display = expanded ? 'block' : 'none';
        detailsToggle.textContent = expanded ? 'Hide details' : 'Show details';
      });

      msgWrapper.appendChild(detailsToggle);
      msgWrapper.appendChild(detailsPanel);
    }

    return msgWrapper;
  }

  function escapeHtml(text: string): string {
    const div = el('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function addChatMessage(role: 'user' | 'assistant', content: string): void {
    const data: MessageData = { role, content, timestamp: new Date() };
    state.chatMessages.push(data);
    const msgEl = renderChatMessage(data);
    // Insert before thinking indicator
    chatMessages.insertBefore(msgEl, thinkingIndicator);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function addAssistantMessage(result: ChatRespondResult): void {
    const data: MessageData = {
      role: 'assistant',
      content: result.answer,
      timestamp: new Date(),
      thinkingSteps: result.thinking_steps,
      toolCalls: result.tool_calls,
      messageId: result.message_id,
      messageType: result.message_type,
    };
    state.chatMessages.push(data);
    const msgEl = renderChatMessage(data);
    // Insert before thinking indicator
    chatMessages.insertBefore(msgEl, thinkingIndicator);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function showThinking(): void {
    thinkingIndicator.style.display = 'flex';
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function hideThinking(): void {
    thinkingIndicator.style.display = 'none';
  }

  function clearChat(): void {
    state.chatMessages = [];
    chatMessages.innerHTML = '';
    chatMessages.appendChild(welcomeMsg);
  }

  function getChatInput(): HTMLInputElement {
    return chatInput;
  }

  function updateSurfaced(items: Array<{ title: string; reason: string; urgency: string }>): void {
    state.surfacedItems = items;
    surfacedList.innerHTML = '';

    if (items.length === 0) {
      const emptyMsg = el('div');
      emptyMsg.style.cssText = `
        text-align: center;
        padding: 20px;
        color: rgba(255,255,255,0.4);
        font-size: 13px;
      `;
      emptyMsg.textContent = 'Nothing surfaced yet';
      surfacedList.appendChild(emptyMsg);
      return;
    }

    items.forEach(item => {
      const itemEl = el('div');
      itemEl.style.cssText = `
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 8px;
        cursor: pointer;
        transition: background 0.2s;
      `;

      const urgencyColor = item.urgency === 'critical' ? '#ef4444'
        : item.urgency === 'high' ? '#f97316'
        : item.urgency === 'medium' ? '#eab308'
        : '#22c55e';

      itemEl.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
          <span style="width: 8px; height: 8px; border-radius: 50%; background: ${urgencyColor};"></span>
          <span style="font-weight: 500; color: #fff; font-size: 13px;">${item.title}</span>
        </div>
        <div style="font-size: 12px; color: rgba(255,255,255,0.5); padding-left: 16px;">
          ${item.reason}
        </div>
      `;

      itemEl.addEventListener('mouseenter', () => {
        itemEl.style.background = 'rgba(255,255,255,0.08)';
      });
      itemEl.addEventListener('mouseleave', () => {
        itemEl.style.background = 'rgba(255,255,255,0.05)';
      });

      surfacedList.appendChild(itemEl);
    });
  }

  return {
    container,
    addChatMessage,
    addAssistantMessage,
    showThinking,
    hideThinking,
    clearChat,
    getChatInput,
    updateSurfaced,
  };
}
