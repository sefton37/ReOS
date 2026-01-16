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
import type { ChatRespondResult, ExtendedThinkingTrace, ThinkingNode, FacetCheck, Tension } from './types';
import { highlight, injectSyntaxHighlightStyles } from './syntaxHighlight';

interface CairnViewCallbacks {
  onSendMessage: (message: string, options?: { extendedThinking?: boolean }) => Promise<void>;
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
  // Extended thinking trace for CAIRN deep reasoning
  extendedThinkingTrace?: ExtendedThinkingTrace | null;
}

interface CairnViewState {
  chatMessages: MessageData[];
  surfacedItems: Array<{ title: string; reason: string; urgency: string }>;
  extendedThinkingEnabled: boolean;
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
  updateSurfaced: (items: Array<{ title: string; reason: string; urgency: string; is_recurring?: boolean; recurrence_frequency?: string; act_color?: string }>) => void;
} {
  const state: CairnViewState = {
    chatMessages: [],
    surfacedItems: [],
    extendedThinkingEnabled: false,
  };

  // Fingerprint of current surfaced items to avoid unnecessary re-renders
  let surfacedFingerprint = '';

  // Inject syntax highlighting styles
  injectSyntaxHighlightStyles();

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

  surfacedPanel.appendChild(surfacedHeader);
  surfacedPanel.appendChild(surfacedList);

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

  // Extended thinking toggle row
  const toggleRow = el('div');
  toggleRow.style.cssText = `
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
  `;

  const thinkingToggle = el('button');
  thinkingToggle.className = 'thinking-toggle';
  thinkingToggle.style.cssText = `
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    background: rgba(147, 51, 234, 0.1);
    border: 1px solid rgba(147, 51, 234, 0.3);
    border-radius: 16px;
    color: rgba(255,255,255,0.6);
    font-size: 12px;
    cursor: pointer;
    transition: all 0.2s;
  `;
  thinkingToggle.innerHTML = `
    <span class="toggle-icon">🧠</span>
    <span class="toggle-label">Think deeply</span>
  `;

  // Update toggle appearance based on state
  function updateToggleAppearance() {
    if (state.extendedThinkingEnabled) {
      thinkingToggle.style.background = 'rgba(147, 51, 234, 0.3)';
      thinkingToggle.style.borderColor = 'rgba(147, 51, 234, 0.6)';
      thinkingToggle.style.color = '#c4b5fd';
      thinkingToggle.innerHTML = `
        <span class="toggle-icon">🧠</span>
        <span class="toggle-label">Think deeply</span>
        <span style="font-size: 10px; background: rgba(147, 51, 234, 0.4); padding: 2px 6px; border-radius: 8px;">ON</span>
      `;
    } else {
      thinkingToggle.style.background = 'rgba(147, 51, 234, 0.1)';
      thinkingToggle.style.borderColor = 'rgba(147, 51, 234, 0.3)';
      thinkingToggle.style.color = 'rgba(255,255,255,0.6)';
      thinkingToggle.innerHTML = `
        <span class="toggle-icon">🧠</span>
        <span class="toggle-label">Think deeply</span>
      `;
    }
  }

  thinkingToggle.addEventListener('click', () => {
    state.extendedThinkingEnabled = !state.extendedThinkingEnabled;
    updateToggleAppearance();
  });

  thinkingToggle.addEventListener('mouseenter', () => {
    if (!state.extendedThinkingEnabled) {
      thinkingToggle.style.background = 'rgba(147, 51, 234, 0.2)';
    }
  });
  thinkingToggle.addEventListener('mouseleave', () => {
    updateToggleAppearance();
  });

  const toggleHint = el('span');
  toggleHint.style.cssText = `
    font-size: 11px;
    color: rgba(255,255,255,0.4);
  `;
  toggleHint.textContent = 'Auto-detects for complex prompts';

  toggleRow.appendChild(thinkingToggle);
  toggleRow.appendChild(toggleHint);

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
    await callbacks.onSendMessage(message, { extendedThinking: state.extendedThinkingEnabled });
  };

  chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleSend();
  });
  sendBtn.addEventListener('click', handleSend);

  inputRow.appendChild(chatInput);
  inputRow.appendChild(sendBtn);
  inputArea.appendChild(toggleRow);
  inputArea.appendChild(inputRow);

  chatPanel.appendChild(chatHeader);
  chatPanel.appendChild(chatMessages);
  chatPanel.appendChild(inputArea);

  // Assemble container
  container.appendChild(surfacedPanel);
  container.appendChild(chatPanel);

  // ============ Functions ============

  function renderChatMessage(data: MessageData): HTMLElement {
    const { role, content, thinkingSteps, toolCalls, extendedThinkingTrace } = data;
    const hasDetails = role === 'assistant' && ((thinkingSteps && thinkingSteps.length > 0) || (toolCalls && toolCalls.length > 0));
    const hasExtendedThinking = role === 'assistant' && extendedThinkingTrace != null;

    const msgWrapper = el('div');
    msgWrapper.style.cssText = `
      max-width: 85%;
      ${role === 'user' ? 'align-self: flex-end; margin-left: auto;' : 'align-self: flex-start;'}
    `;

    // Extended Thinking panel (above the message when present)
    if (hasExtendedThinking && extendedThinkingTrace) {
      const thinkingPanel = renderExtendedThinkingPanel(extendedThinkingTrace);
      msgWrapper.appendChild(thinkingPanel);
    }

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
    // Render content with syntax highlighting for code blocks
    if (content.includes('```')) {
      msgEl.innerHTML = renderContentWithCodeBlocks(content);
    } else {
      msgEl.textContent = content;
    }
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

  /** Render the Extended Thinking collapsible panel */
  function renderExtendedThinkingPanel(trace: ExtendedThinkingTrace): HTMLElement {
    const panel = el('div');
    panel.className = 'extended-thinking-panel';
    panel.style.cssText = `
      margin-bottom: 12px;
      border: 1px solid rgba(147, 51, 234, 0.3);
      border-radius: 12px;
      background: rgba(147, 51, 234, 0.05);
      overflow: hidden;
    `;

    // Summary counts for collapsed view
    const understoodCount = trace.understood?.length || 0;
    const ambiguousCount = trace.ambiguous?.length || 0;
    const assumptionCount = trace.assumptions?.length || 0;
    const tensionCount = trace.tensions?.length || 0;
    const confidencePercent = Math.round((trace.final_confidence || 0) * 100);

    // Header (always visible)
    const header = el('div');
    header.style.cssText = `
      padding: 12px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      background: rgba(147, 51, 234, 0.1);
    `;
    header.innerHTML = `
      <div style="display: flex; align-items: center; gap: 8px;">
        <span style="font-size: 16px;">🧠</span>
        <span style="font-weight: 600; color: #a78bfa;">CAIRN's Thinking</span>
        <span style="font-size: 11px; padding: 2px 8px; border-radius: 10px; background: rgba(147, 51, 234, 0.2); color: #c4b5fd;">
          ${confidencePercent}% confident
        </span>
      </div>
      <div style="display: flex; align-items: center; gap: 12px;">
        <div style="display: flex; gap: 8px; font-size: 11px; color: rgba(255,255,255,0.5);">
          ${understoodCount > 0 ? `<span title="Understood">✓ ${understoodCount}</span>` : ''}
          ${ambiguousCount > 0 ? `<span title="Ambiguous" style="color: #fbbf24;">? ${ambiguousCount}</span>` : ''}
          ${assumptionCount > 0 ? `<span title="Assumptions" style="color: #60a5fa;">⚠ ${assumptionCount}</span>` : ''}
          ${tensionCount > 0 ? `<span title="Tensions" style="color: #f87171;">⚡ ${tensionCount}</span>` : ''}
        </div>
        <span class="expand-icon" style="color: rgba(255,255,255,0.4); transition: transform 0.2s;">▼</span>
      </div>
    `;

    // Content (collapsible)
    const content = el('div');
    content.className = 'thinking-content';
    content.style.cssText = `
      display: none;
      padding: 16px;
      border-top: 1px solid rgba(147, 51, 234, 0.2);
      max-height: 400px;
      overflow-y: auto;
    `;

    // Build content sections
    let contentHTML = '';

    // Phase 1: What was understood
    if (understoodCount > 0) {
      contentHTML += `
        <div style="margin-bottom: 16px;">
          <div style="display: flex; align-items: center; gap: 6px; color: #22c55e; font-weight: 600; margin-bottom: 8px;">
            <span>✓</span>
            <span>Understood</span>
          </div>
          <ul style="margin: 0; padding-left: 20px; color: rgba(255,255,255,0.8); font-size: 13px; line-height: 1.6;">
            ${trace.understood.map(node => `<li>${escapeHtml(node.content)} <span style="color: rgba(255,255,255,0.4); font-size: 11px;">(${Math.round(node.confidence * 100)}%)</span></li>`).join('')}
          </ul>
        </div>
      `;
    }

    // Ambiguous items
    if (ambiguousCount > 0) {
      contentHTML += `
        <div style="margin-bottom: 16px;">
          <div style="display: flex; align-items: center; gap: 6px; color: #fbbf24; font-weight: 600; margin-bottom: 8px;">
            <span>?</span>
            <span>Ambiguous</span>
          </div>
          <ul style="margin: 0; padding-left: 20px; color: rgba(255,255,255,0.8); font-size: 13px; line-height: 1.6;">
            ${trace.ambiguous.map(node => `<li>${escapeHtml(node.content)}</li>`).join('')}
          </ul>
        </div>
      `;
    }

    // Phase 2: Assumptions made
    if (assumptionCount > 0) {
      contentHTML += `
        <div style="margin-bottom: 16px;">
          <div style="display: flex; align-items: center; gap: 6px; color: #60a5fa; font-weight: 600; margin-bottom: 8px;">
            <span>⚠</span>
            <span>Assumptions I made</span>
          </div>
          <ul style="margin: 0; padding-left: 20px; color: rgba(255,255,255,0.8); font-size: 13px; line-height: 1.6;">
            ${trace.assumptions.map(node => `<li>${escapeHtml(node.content)} <span style="color: rgba(255,255,255,0.4); font-size: 11px;">(${Math.round(node.confidence * 100)}%)</span></li>`).join('')}
          </ul>
        </div>
      `;
    }

    // Questions for user
    if (trace.questions_for_user && trace.questions_for_user.length > 0) {
      contentHTML += `
        <div style="margin-bottom: 16px;">
          <div style="display: flex; align-items: center; gap: 6px; color: #c084fc; font-weight: 600; margin-bottom: 8px;">
            <span>❓</span>
            <span>Questions for you</span>
          </div>
          <ul style="margin: 0; padding-left: 20px; color: rgba(255,255,255,0.8); font-size: 13px; line-height: 1.6;">
            ${trace.questions_for_user.map(q => `<li>${escapeHtml(q)}</li>`).join('')}
          </ul>
        </div>
      `;
    }

    // Phase 3: Identity checks
    if (trace.identity_facets_checked && trace.identity_facets_checked.length > 0) {
      contentHTML += `
        <div style="margin-bottom: 16px;">
          <div style="display: flex; align-items: center; gap: 6px; color: #a78bfa; font-weight: 600; margin-bottom: 8px;">
            <span>🔍</span>
            <span>Checked against your identity</span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 8px;">
            ${trace.identity_facets_checked.map(fc => {
              const alignmentColor = fc.alignment > 0.3 ? '#22c55e' : fc.alignment < -0.3 ? '#ef4444' : '#fbbf24';
              const alignmentText = fc.alignment > 0.3 ? 'aligns' : fc.alignment < -0.3 ? 'conflicts' : 'neutral';
              return `
                <div style="padding: 8px 12px; background: rgba(255,255,255,0.05); border-radius: 6px; font-size: 13px;">
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="color: #fff;">"${escapeHtml(fc.facet_name)}"</span>
                    <span style="color: ${alignmentColor};">— ${alignmentText} (${fc.alignment.toFixed(1)})</span>
                  </div>
                  <div style="color: rgba(255,255,255,0.5); font-size: 11px; margin-top: 4px;">
                    From: ${escapeHtml(fc.facet_source)}
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    }

    // Tensions detected
    if (tensionCount > 0) {
      contentHTML += `
        <div style="margin-bottom: 16px;">
          <div style="display: flex; align-items: center; gap: 6px; color: #f87171; font-weight: 600; margin-bottom: 8px;">
            <span>⚡</span>
            <span>Tensions detected</span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 8px;">
            ${trace.tensions.map(t => {
              const severityColor = t.severity === 'high' ? '#ef4444' : t.severity === 'medium' ? '#f97316' : '#fbbf24';
              return `
                <div style="padding: 12px; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 8px;">
                  <div style="font-size: 13px; color: #fff; margin-bottom: 6px;">
                    ${escapeHtml(t.description)}
                  </div>
                  <div style="font-size: 11px; color: rgba(255,255,255,0.6); margin-bottom: 6px;">
                    Your "<span style="color: #a78bfa;">${escapeHtml(t.identity_facet)}</span>" vs
                    "<span style="color: #60a5fa;">${escapeHtml(t.prompt_aspect)}</span>"
                  </div>
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 10px; padding: 2px 6px; border-radius: 4px; background: ${severityColor}20; color: ${severityColor}; text-transform: uppercase;">
                      ${t.severity}
                    </span>
                    <span style="font-size: 11px; color: rgba(255,255,255,0.5);">
                      ${escapeHtml(t.recommendation)}
                    </span>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    }

    // Decision summary
    const decisionIcon = trace.decision === 'respond' ? '✅' : trace.decision === 'ask' ? '❓' : '⏸️';
    const decisionText = trace.decision === 'respond' ? 'Proceeding with response' :
                         trace.decision === 'ask' ? 'Need to ask you first' : 'Deferring for later';
    contentHTML += `
      <div style="padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.1);">
        <div style="display: flex; align-items: center; gap: 8px; font-size: 12px;">
          <span>${decisionIcon}</span>
          <span style="color: rgba(255,255,255,0.6);">Decision: <span style="color: #fff;">${decisionText}</span></span>
        </div>
      </div>
    `;

    content.innerHTML = contentHTML;

    // Toggle behavior
    let expanded = false;
    const expandIcon = header.querySelector('.expand-icon') as HTMLElement;

    header.addEventListener('click', () => {
      expanded = !expanded;
      content.style.display = expanded ? 'block' : 'none';
      if (expandIcon) {
        expandIcon.style.transform = expanded ? 'rotate(180deg)' : 'rotate(0deg)';
      }
    });

    panel.appendChild(header);
    panel.appendChild(content);

    return panel;
  }

  function escapeHtml(text: string): string {
    const div = el('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Parse content and render code blocks with syntax highlighting.
   * Handles markdown-style ``` code blocks.
   */
  function renderContentWithCodeBlocks(content: string): string {
    // Match code blocks: ```language\ncode\n```
    const codeBlockRegex = /```(\w*)\n([\s\S]*?)```/g;
    let result = '';
    let lastIndex = 0;

    for (const match of content.matchAll(codeBlockRegex)) {
      const [fullMatch, language, code] = match;
      const index = match.index!;

      // Add text before the code block
      if (index > lastIndex) {
        result += escapeHtml(content.slice(lastIndex, index));
      }

      // Add the highlighted code block
      const lang = language || 'text';
      const highlightedCode = highlight(code.trimEnd(), lang);
      result += `
        <div style="
          margin: 8px 0;
          background: rgba(0,0,0,0.4);
          border-radius: 8px;
          overflow: hidden;
        ">
          <div style="
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 6px 12px;
            background: rgba(0,0,0,0.3);
            font-size: 11px;
            color: rgba(255,255,255,0.5);
          ">
            <span>${lang}</span>
          </div>
          <pre style="
            margin: 0;
            padding: 12px;
            font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
            font-size: 12px;
            line-height: 1.5;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-word;
          "><code>${highlightedCode}</code></pre>
        </div>
      `;

      lastIndex = index + fullMatch.length;
    }

    // Add any remaining text after the last code block
    if (lastIndex < content.length) {
      result += escapeHtml(content.slice(lastIndex));
    }

    // Replace newlines with <br> in non-code content
    result = result.replace(/\n/g, '<br>');

    return result;
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
      extendedThinkingTrace: result.extended_thinking_trace,
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

  function updateSurfaced(items: Array<{
    title: string;
    reason: string;
    urgency: string;
    is_recurring?: boolean;
    recurrence_frequency?: string;
    next_occurrence?: string;
    entity_type?: string;
    entity_id?: string;
    act_id?: string;
    scene_id?: string;
    act_title?: string;
    act_color?: string;
  }>): void {
    // Compute fingerprint to detect changes and avoid unnecessary re-renders
    const newFingerprint = JSON.stringify(items.map(i => ({
      id: i.entity_id,
      t: i.title,
      u: i.urgency,
      a: i.act_id,
    })));

    if (newFingerprint === surfacedFingerprint) {
      return;  // No changes, skip DOM update
    }

    surfacedFingerprint = newFingerprint;
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

      // Recurring icon (just the icon, no date)
      const recurringIcon = item.is_recurring
        ? `<span title="Recurring ${item.recurrence_frequency?.toLowerCase() || ''}" style="font-size: 11px; margin-left: 4px;">🔄</span>`
        : '';

      // Act label with dynamic color
      const actColor = item.act_color || '#9333ea';  // Default to purple if no color set
      const actLabel = item.act_title
        ? `<span style="font-size: 10px; margin-left: 6px; padding: 2px 6px; background: ${actColor}33; color: ${actColor}; border-radius: 4px;">Act: ${escapeHtml(item.act_title)}</span>`
        : '';

      itemEl.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
          <span style="width: 8px; height: 8px; border-radius: 50%; background: ${urgencyColor};"></span>
          <span style="font-weight: 500; color: #fff; font-size: 13px;">${escapeHtml(item.title)}</span>
          ${recurringIcon}
          ${actLabel}
        </div>
        <div style="font-size: 12px; color: rgba(255,255,255,0.5); padding-left: 16px;">
          ${escapeHtml(item.reason)}
        </div>
      `;

      itemEl.addEventListener('mouseenter', () => {
        itemEl.style.background = 'rgba(255,255,255,0.08)';
      });
      itemEl.addEventListener('mouseleave', () => {
        itemEl.style.background = 'rgba(255,255,255,0.05)';
      });

      // Click to navigate to Beat in The Play
      if (item.entity_type === 'beat' && item.act_id && item.scene_id) {
        itemEl.addEventListener('click', () => {
          // Dispatch custom event to open The Play at this Beat
          const event = new CustomEvent('openPlayBeat', {
            detail: {
              actId: item.act_id,
              sceneId: item.scene_id,
              beatId: item.entity_id,
            },
          });
          window.dispatchEvent(event);
        });
      }

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
