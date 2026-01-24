/**
 * ReOS Desktop Application - Natural Language Linux
 *
 * Main entry point for the Tauri-based desktop UI.
 * Communicates with the Python kernel via JSON-RPC over stdio.
 */
import { WebviewWindow, getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow';
import { open as openDialog } from '@tauri-apps/plugin-dialog';

import './style.css';

// Modular imports
import {
  kernelRequest,
  KernelError,
  AuthenticationError,
  isAuthenticated,
  validateSession,
  logout,
  getSessionUsername,
} from './kernel';
import { checkSessionOrLogin, showLockOverlay } from './lockScreen';
import { el, rowHeader, label, textInput, textArea, smallButton } from './dom';
import { createPlayOverlay } from './playOverlay';
import { createSettingsOverlay } from './settingsOverlay';
import { createContextOverlay } from './contextOverlay';
import { renderCollapsedDiffPreview } from './diffPreview';
import { createDiffPreviewOverlay } from './diffPreviewOverlay';
import { createCodeModeView } from './codeModeView';
import { createCairnView } from './cairnView';
import { createArchiveReviewOverlay, ArchivePreview, ArchiveReviewResult } from './archiveReviewOverlay';
import { buildPlayWindow } from './playWindow';
import type {
  ChatRespondResult,
  SystemInfoResult,
  SystemLiveStateResult,
  ServiceActionResult,
  ContainerActionResult,
  ExecutionOutputResult,
  PlanPreviewResult,
  PlanApproveResult,
  ExecutionStatusResult,
  PlayMeReadResult,
  PlayActsListResult,
  PlayScenesListResult,
  PlayBeatsListResult,
  PlayActsCreateResult,
  PlayKbListResult,
  PlayKbReadResult,
  PlayKbWritePreviewResult,
  PlayKbWriteApplyResult,
  ApprovalPendingResult,
  ApprovalRespondResult,
  ApprovalExplainResult,
  ContextStatsResult,
  ContextToggleResult,
  CodeExecutionState,
  CodeExecStartResult,
  CodeExecCancelResult,
} from './types';

function buildUi() {
  const query = new URLSearchParams(window.location.search);
  if (query.get('view') === 'me') {
    void buildMeWindow();
    return;
  }
  if (query.get('view') === 'dashboard') {
    void buildDashboardWindow();
    return;
  }
  if (query.get('view') === 'play') {
    void buildPlayWindow();
    return;
  }

  const root = document.getElementById('app');
  if (!root) return;

  root.innerHTML = '';

  const shell = el('div');
  shell.className = 'shell';
  shell.style.display = 'flex';
  shell.style.height = '100vh';
  shell.style.fontFamily = 'system-ui, sans-serif';

  const nav = el('div');
  nav.className = 'nav';
  nav.style.width = '280px';
  nav.style.borderRight = '1px solid #ddd';
  nav.style.padding = '12px';
  nav.style.overflow = 'auto';

  const navTitle = el('div');
  navTitle.textContent = 'Talking Rock for Linux';
  navTitle.style.fontWeight = '600';
  navTitle.style.fontSize = '16px';
  navTitle.style.marginBottom = '12px';

  // ============ Agent Selector ============
  type AgentType = 'cairn' | 'riva' | 'reos';
  let currentAgent: AgentType = 'cairn';

  const agentSelector = el('div');
  agentSelector.className = 'agent-selector';
  agentSelector.style.cssText = `
    display: flex;
    gap: 4px;
    margin-bottom: 16px;
    padding: 4px;
    background: rgba(0,0,0,0.2);
    border-radius: 8px;
  `;

  const agentButtons: Record<AgentType, HTMLButtonElement> = {
    cairn: el('button') as HTMLButtonElement,
    riva: el('button') as HTMLButtonElement,
    reos: el('button') as HTMLButtonElement,
  };

  const agentConfig: Record<AgentType, { label: string; icon: string; tooltip: string }> = {
    cairn: { label: 'CAIRN', icon: '🪨', tooltip: 'Attention Minder - Conversations & Knowledge' },
    riva: { label: 'RIVA', icon: '⚡', tooltip: 'Code Mode - Build & Modify Code' },
    reos: { label: 'ReOS', icon: '💻', tooltip: 'Terminal - Direct System Access' },
  };

  const updateAgentButtons = () => {
    Object.entries(agentButtons).forEach(([agent, btn]) => {
      const isActive = agent === currentAgent;
      btn.style.cssText = `
        flex: 1;
        padding: 8px 4px;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        font-size: 11px;
        font-weight: 500;
        transition: all 0.2s;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 2px;
        ${isActive
          ? 'background: rgba(59, 130, 246, 0.3); color: #fff;'
          : 'background: transparent; color: rgba(255,255,255,0.5);'
        }
      `;
    });
  };

  Object.entries(agentConfig).forEach(([agent, config]) => {
    const btn = agentButtons[agent as AgentType];
    btn.innerHTML = `<span style="font-size: 16px;">${config.icon}</span><span>${config.label}</span>`;
    btn.title = config.tooltip;
    btn.addEventListener('click', () => {
      if (agent === 'reos') {
        // Open terminal window
        openTerminal();
      } else {
        currentAgent = agent as AgentType;
        updateAgentButtons();
        switchAgentView(agent as AgentType);
      }
    });
    agentSelector.appendChild(btn);
  });

  updateAgentButtons();

  // System Status Section
  const systemSection = el('div');
  systemSection.className = 'system-section';

  const systemHeader = el('div');
  systemHeader.textContent = 'System Status';
  systemHeader.style.fontWeight = '600';
  systemHeader.style.marginBottom = '8px';
  systemHeader.style.fontSize = '13px';
  systemHeader.style.color = '#666';

  const systemStatus = el('div');
  systemStatus.className = 'system-status';
  systemStatus.style.fontSize = '12px';
  systemStatus.style.marginBottom = '12px';
  systemStatus.innerHTML = '<span style="opacity: 0.6">Loading...</span>';

  systemSection.appendChild(systemHeader);
  systemSection.appendChild(systemStatus);

  // Shared nav button style
  const navBtnStyle = (btn: HTMLElement) => {
    btn.style.padding = '10px';
    btn.style.fontSize = '12px';
    btn.style.fontWeight = '500';
    btn.style.border = '1px solid rgba(255, 255, 255, 0.15)';
    btn.style.borderRadius = '8px';
    btn.style.background = 'rgba(255, 255, 255, 0.08)';
    btn.style.color = '#e5e7eb';
    btn.style.cursor = 'pointer';
    btn.style.width = '100%';
    btn.style.textAlign = 'left';
  };

  // System Dashboard Button
  const dashboardBtn = el('button');
  dashboardBtn.textContent = 'Open System Dashboard';
  dashboardBtn.style.marginTop = '12px';
  navBtnStyle(dashboardBtn);

  // The Play Button - opens the Play window
  const playBtn = el('button');
  playBtn.textContent = 'The Play';
  playBtn.title = 'Open The Play - your story, acts, and scenes';
  navBtnStyle(playBtn);
  playBtn.style.marginTop = '12px';

  // Nav content container (top section)
  const navContent = el('div');
  navContent.className = 'nav-content';
  navContent.style.cssText = 'flex: 1;';

  navContent.appendChild(navTitle);
  navContent.appendChild(agentSelector);

  // ============ Context Usage Indicator (opens Context Overlay) ============
  const navContextMeter = el('div');
  navContextMeter.className = 'nav-context-meter';
  navContextMeter.title = 'Click to view context details';
  navContextMeter.style.cssText = `
    margin-bottom: 12px;
    padding: 10px 12px;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.2s;
  `;

  const contextUsageBar = el('div');
  contextUsageBar.style.cssText = `
    height: 6px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 3px;
    overflow: hidden;
    margin-bottom: 6px;
  `;

  const contextUsageFill = el('div');
  contextUsageFill.style.cssText = `
    height: 100%;
    width: 0%;
    background: #22c55e;
    border-radius: 3px;
    transition: width 0.3s, background 0.3s;
  `;
  contextUsageBar.appendChild(contextUsageFill);

  const contextUsageLabel = el('div');
  contextUsageLabel.style.cssText = `
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 11px;
    color: rgba(255, 255, 255, 0.6);
  `;
  contextUsageLabel.innerHTML = `
    <span>🧠 Context</span>
    <span class="context-usage-value">Loading...</span>
  `;

  navContextMeter.appendChild(contextUsageBar);
  navContextMeter.appendChild(contextUsageLabel);

  // Update context meter periodically
  let lastContextMeterUpdate = 0;
  async function updateNavContextMeter() {
    try {
      const stats = await kernelRequest('context/stats', {
        conversation_id: currentConversationId,
      }) as ContextStatsResult;

      const percent = Math.min(100, stats.usage_percent);
      const color = stats.warning_level === 'critical' ? '#ef4444' :
                    stats.warning_level === 'warning' ? '#f59e0b' : '#22c55e';

      contextUsageFill.style.width = `${percent}%`;
      contextUsageFill.style.background = color;

      const valueEl = contextUsageLabel.querySelector('.context-usage-value');
      if (valueEl) {
        valueEl.textContent = `${Math.round(percent)}% • ${stats.available_tokens.toLocaleString()} left`;
        (valueEl as HTMLElement).style.color = color;
      }
    } catch {
      // Silently fail - context stats may not be available
    }
  }

  // Poll context every 30s
  setInterval(() => {
    const now = Date.now();
    if (now - lastContextMeterUpdate > 30000) {
      lastContextMeterUpdate = now;
      void updateNavContextMeter();
    }
  }, 5000);

  // Initial load
  setTimeout(() => void updateNavContextMeter(), 1000);

  navContextMeter.addEventListener('mouseenter', () => {
    navContextMeter.style.background = 'rgba(0, 0, 0, 0.3)';
  });
  navContextMeter.addEventListener('mouseleave', () => {
    navContextMeter.style.background = 'rgba(0, 0, 0, 0.2)';
  });

  // Note: Click handler to open contextOverlay is added after contextOverlay is created

  navContent.appendChild(navContextMeter);
  navContent.appendChild(systemSection);
  navContent.appendChild(dashboardBtn);
  navContent.appendChild(playBtn);

  // Settings button (bottom of nav)
  const settingsBtn = el('button');
  settingsBtn.className = 'settings-btn';
  settingsBtn.innerHTML = '⚙️ Settings';
  settingsBtn.style.cssText = `
    width: 100%;
    padding: 10px 12px;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    color: rgba(255,255,255,0.8);
    cursor: pointer;
    font-size: 13px;
    text-align: left;
    transition: background 0.2s;
    margin-top: 8px;
  `;
  settingsBtn.addEventListener('mouseenter', () => {
    settingsBtn.style.background = 'rgba(255,255,255,0.1)';
  });
  settingsBtn.addEventListener('mouseleave', () => {
    settingsBtn.style.background = 'rgba(255,255,255,0.05)';
  });

  // Make nav flex column
  nav.style.display = 'flex';
  nav.style.flexDirection = 'column';

  nav.appendChild(navContent);
  nav.appendChild(settingsBtn);

  // ============ RIVA View (Code Mode) ============
  const codeModeView = createCodeModeView({
    onSendMessage: async (message: string) => {
      // Will be wired up in onSend below
      return handleChatMessage(message);
    },
    onCancelExecution: async () => {
      if (activeCodeExecId) {
        await kernelRequest('code-exec/cancel', { execution_id: activeCodeExecId });
      }
    },
    kernelRequest,
  });

  // ============ Archive Review Overlay ============
  let currentArchivePreview: ArchivePreview | null = null;

  const archiveReviewOverlay = createArchiveReviewOverlay({
    onConfirm: async (result: ArchiveReviewResult) => {
      if (!currentConversationId || !currentArchivePreview) return;

      try {
        const archiveResult = await kernelRequest('conversation/archive/confirm', {
          conversation_id: currentConversationId,
          title: result.editedTitle,
          summary: result.editedSummary,
          act_id: currentArchivePreview.linked_act_id,
          knowledge_entries: result.approvedEntries,
          additional_notes: result.additionalNotes,
          rating: result.rating,
        }) as { archive_id: string; title: string; message_count: number; knowledge_entries_added: number };

        // Show success message in CAIRN view
        let successMsg = `Archived "${archiveResult.title}" (${archiveResult.message_count} messages)`;
        if (archiveResult.knowledge_entries_added > 0) {
          successMsg += `. Saved ${archiveResult.knowledge_entries_added} knowledge entries`;
        }
        successMsg += '.';
        cairnView.addChatMessage('assistant', successMsg);

        // Clear the chat
        cairnView.clearChat();
        currentConversationId = null;
        currentArchivePreview = null;

      } catch (e) {
        cairnView.addChatMessage('assistant', `Archive failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
      }
    },
    onCancel: () => {
      currentArchivePreview = null;
      cairnView.addChatMessage('assistant', 'Archive cancelled.');
    },
    getActTitle: async (actId: string) => {
      try {
        const result = await kernelRequest('play/acts/list', {}) as { acts: Array<{ act_id: string; title: string }> };
        const act = result.acts.find(a => a.act_id === actId);
        return act?.title || null;
      } catch {
        return null;
      }
    },
  });

  // Add overlay to document
  document.body.appendChild(archiveReviewOverlay.container);

  // ============ CAIRN View (Conversational) ============
  const cairnView = createCairnView({
    onSendMessage: async (message: string, options?: { extendedThinking?: boolean }) => {
      return handleCairnMessage(message, options);
    },
    kernelRequest,
    getConversationId: () => currentConversationId,
    onConversationCleared: () => {
      currentConversationId = null;
    },
    showArchiveReview: (preview: ArchivePreview) => {
      currentArchivePreview = preview;
      archiveReviewOverlay.show(preview);
    },
  });

  // Load attention items at startup for "What Needs My Attention" section (next 7 days)
  void (async () => {
    try {
      const result = await kernelRequest('cairn/attention', { hours: 168, limit: 50 }) as {
        count: number;
        items: Array<{
          entity_type: string;
          entity_id: string;
          title: string;
          reason: string;
          urgency: string;
          calendar_start?: string;
          calendar_end?: string;
          is_recurring?: boolean;
          recurrence_frequency?: string;
          next_occurrence?: string;
          act_id?: string;
          scene_id?: string;
          act_title?: string;
          act_color?: string;
        }>;
      };
      if (result.items && result.items.length > 0) {
        cairnView.updateSurfaced(result.items.map(item => ({
          title: item.title,
          reason: item.reason,
          urgency: item.urgency,
          is_recurring: item.is_recurring,
          recurrence_frequency: item.recurrence_frequency,
          next_occurrence: item.next_occurrence,
          entity_type: item.entity_type,
          entity_id: item.entity_id,
          act_id: item.act_id,
          scene_id: item.scene_id,
          act_title: item.act_title,
          act_color: item.act_color,
        })));
      }
    } catch (e) {
      console.log('Could not load attention items:', e);
      // Silently fail - the panel will just show "Nothing surfaced yet"
    }
  })();

  // Refresh attention items - called after Play mutations and on polling interval
  async function refreshAttentionItems(): Promise<void> {
    try {
      const result = await kernelRequest('cairn/attention', { hours: 168, limit: 50 }) as {
        count: number;
        items: Array<{
          entity_type: string;
          entity_id: string;
          title: string;
          reason: string;
          urgency: string;
          calendar_start?: string;
          calendar_end?: string;
          is_recurring?: boolean;
          recurrence_frequency?: string;
          next_occurrence?: string;
          act_id?: string;
          scene_id?: string;
          act_title?: string;
          act_color?: string;
        }>;
      };
      cairnView.updateSurfaced(result.items.map(item => ({
        title: item.title,
        reason: item.reason,
        urgency: item.urgency,
        is_recurring: item.is_recurring,
        recurrence_frequency: item.recurrence_frequency,
        next_occurrence: item.next_occurrence,
        entity_type: item.entity_type,
        entity_id: item.entity_id,
        act_id: item.act_id,
        scene_id: item.scene_id,
        act_title: item.act_title,
        act_color: item.act_color,
      })));
    } catch (e) {
      console.log('Could not refresh attention items:', e);
    }
  }

  // Auto-archive conversation on window close
  const autoArchiveOnClose = async (): Promise<void> => {
    if (!currentConversationId) return;

    try {
      // Archive the current conversation silently
      await kernelRequest('conversation/archive', {
        conversation_id: currentConversationId,
        auto_link: true,
        extract_knowledge: true,
      });
      console.log('Auto-archived conversation on close');
    } catch (e) {
      console.error('Failed to auto-archive on close:', e);
    }
  };

  // Auto-archive on close using beforeunload (best-effort, may not complete)
  window.addEventListener('beforeunload', () => {
    if (currentConversationId) {
      void autoArchiveOnClose();
    }
  });

  // Adaptive polling for attention items: 10s when user active, 60s when idle
  let lastActivityTime = Date.now();
  const ACTIVE_POLL_INTERVAL = 10000;  // 10 seconds when active
  const IDLE_POLL_INTERVAL = 60000;    // 60 seconds when idle
  const IDLE_THRESHOLD = 30000;        // Consider idle after 30 seconds of no activity

  function updateActivityTime(): void {
    lastActivityTime = Date.now();
  }

  // Track user activity
  document.addEventListener('mousemove', updateActivityTime);
  document.addEventListener('keydown', updateActivityTime);
  document.addEventListener('click', updateActivityTime);

  // Start adaptive polling
  function scheduleNextPoll(): void {
    const isIdle = Date.now() - lastActivityTime > IDLE_THRESHOLD;
    const interval = isIdle ? IDLE_POLL_INTERVAL : ACTIVE_POLL_INTERVAL;

    setTimeout(() => {
      void refreshAttentionItems().then(scheduleNextPoll);
    }, interval);
  }

  // Start polling after a small delay to avoid duplicate initial fetch
  setTimeout(scheduleNextPoll, ACTIVE_POLL_INTERVAL);

  // Handle CAIRN chat messages (default conversational mode)
  async function handleCairnMessage(message: string, options?: { extendedThinking?: boolean }): Promise<void> {
    // Show thinking indicator while waiting for response
    cairnView.showThinking();
    try {
      const result = (await kernelRequest('chat/respond', {
        text: message,
        conversation_id: currentConversationId,
        agent_type: currentAgent,  // Pass current agent for persona selection
        // Extended thinking: true=force on, undefined=auto-detect, false would disable
        // When toggle is on, force it. When off, let backend auto-detect for complex prompts.
        extended_thinking: options?.extendedThinking === true ? true : undefined,
        // No use_code_mode flag - CAIRN is the default conversational agent
      })) as ChatRespondResult;
      cairnView.hideThinking();
      if (result.conversation_id) {
        currentConversationId = result.conversation_id;
      }
      // Use addAssistantMessage to include full response data (thinking steps, tool calls)
      cairnView.addAssistantMessage(result);

      // Refresh attention items after CAIRN chat - beat moves may have changed act assignments
      void refreshAttentionItems();
    } catch (error) {
      cairnView.hideThinking();
      cairnView.addChatMessage('assistant', `Error: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  }

  // ============ Main View Container ============
  const mainViewContainer = el('div');
  mainViewContainer.className = 'main-view-container';
  mainViewContainer.style.cssText = `
    flex: 1;
    display: flex;
    overflow: hidden;
  `;
  mainViewContainer.appendChild(cairnView.container);
  mainViewContainer.appendChild(codeModeView.container);

  // Start with CAIRN view visible, RIVA hidden
  cairnView.container.style.display = 'flex';
  codeModeView.container.style.display = 'none';

  // Switch between agent views
  function switchAgentView(agent: AgentType): void {
    if (agent === 'cairn') {
      cairnView.container.style.display = 'flex';
      codeModeView.container.style.display = 'none';
    } else if (agent === 'riva') {
      cairnView.container.style.display = 'none';
      codeModeView.container.style.display = 'flex';
    }
  }

  // Open terminal window
  async function openTerminal(): Promise<void> {
    try {
      const result = (await kernelRequest('system/open-terminal', {})) as { success: boolean; terminal?: string; error?: string };
      if (!result.success) {
        console.error('Failed to open terminal:', result.error);
      }
    } catch (error) {
      console.error('Failed to open terminal:', error);
    }
  }

  // Context state for the context meter
  let currentConversationId: string | null = null;

  // Note: Context meter and chat actions are now integrated into the Code Mode view header
  // The old center panel UI (chatHeader, chatLog, inputRow, inspection) has been replaced
  // by the Code Mode view which provides execution panel + chat sidebar

  // Store for message data (keyed by content for lookup)
  const messageDataStore: ChatRespondResult[] = [];

  // Legacy stub elements for The Play inspector (now handled by overlay)
  // These are kept to avoid breaking old code that references them
  const inspectionTitle = el('div') as HTMLDivElement;
  const inspectionBody = el('div') as HTMLDivElement;
  // Note: The Play inspector is now shown in the overlay, not the main view

  // Legacy stub elements for context meter (removed from visible UI)
  // The context is now tracked internally but not shown in the new Code Mode view
  const meterFill = el('div') as HTMLDivElement;
  const meterText = el('span') as HTMLSpanElement;
  // These stubs prevent errors when updateContextMeter is called

  // Legacy stub for chatLog (now handled by Code Mode view chat sidebar)
  const chatLog = el('div') as HTMLDivElement;
  // Note: Use codeModeView.clearChat() for clearing chat

  // Code Mode execution tracking (needed by codeModeView callbacks)
  let codeExecActive = false;
  let activeCodeExecId: string | null = null;
  let codeExecState: Partial<CodeExecutionState> | null = null;
  let codeExecPollInterval: ReturnType<typeof setInterval> | null = null;

  // ============ Shell Assembly ============
  // New layout: nav (280px) | mainViewContainer (CAIRN or RIVA view)
  shell.appendChild(nav);
  shell.appendChild(mainViewContainer);

  root.appendChild(shell);

  // Create Play overlay
  const playOverlay = createPlayOverlay(() => {
    // Callback when overlay closes
    playInspectorActive = false;
  });
  root.appendChild(playOverlay.element);

  // Create Settings overlay
  const settingsOverlay = createSettingsOverlay();
  root.appendChild(settingsOverlay.element);

  // Wire up settings button
  settingsBtn.addEventListener('click', () => {
    settingsOverlay.show();
  });

  // Create Context overlay
  const contextOverlay = createContextOverlay();
  root.appendChild(contextOverlay.element);

  // Wire up nav context meter to open the overlay
  navContextMeter.addEventListener('click', () => {
    contextOverlay.show(currentConversationId);
    // Update meter after viewing (user might have toggled sources)
    setTimeout(() => void updateNavContextMeter(), 500);
  });

  // Create Diff Preview overlay for code changes
  const diffPreviewOverlay = createDiffPreviewOverlay();
  root.appendChild(diffPreviewOverlay.element);

  function createCopyButton(getText: () => string): HTMLButtonElement {
    const btn = el('button') as HTMLButtonElement;
    btn.className = 'copy-btn';
    btn.innerHTML = '📋';
    btn.title = 'Copy to clipboard';
    btn.style.cssText = `
      position: absolute;
      top: 4px;
      right: 4px;
      background: rgba(255,255,255,0.1);
      border: none;
      border-radius: 4px;
      padding: 4px 6px;
      cursor: pointer;
      opacity: 0;
      transition: opacity 0.2s;
      font-size: 12px;
    `;
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        await navigator.clipboard.writeText(getText());
        btn.innerHTML = '✓';
        setTimeout(() => { btn.innerHTML = '📋'; }, 1500);
      } catch {
        btn.innerHTML = '✗';
        setTimeout(() => { btn.innerHTML = '📋'; }, 1500);
      }
    });
    return btn;
  }

  // Helper to append messages to the Code Mode view's chat sidebar
  function append(role: 'user' | 'reos', text: string, data?: ChatRespondResult) {
    codeModeView.addChatMessage(role === 'user' ? 'user' : 'assistant', text, data);
    if (data) {
      messageDataStore.push(data);
    }
  }

  // Thinking indicator - we'll simulate with a placeholder message that gets replaced
  let pendingThinkingResolve: (() => void) | null = null;

  function appendThinking(): { remove: () => void } {
    // Add a temporary "thinking..." message that will be replaced
    codeModeView.addChatMessage('assistant', '...');
    return {
      remove: () => {
        // The actual response will be added which replaces this conceptually
        // In the new UI, the thinking animation is shown differently
      }
    };
  }

  let activeActId: string | null = null;
  let actsCache: PlayActsListResult['acts'] = [];
  let selectedSceneId: string | null = null;
  let selectedBeatId: string | null = null;

  let scenesCache: PlayScenesListResult['scenes'] = [];
  let beatsCache: PlayBeatsListResult['beats'] = [];

  let kbSelectedPath = 'kb.md';
  let kbTextDraft = '';
  let kbPreview: PlayKbWritePreviewResult | null = null;

  // Flag to track if "The Play" view is active in the inspection panel
  let playInspectorActive = false;

  // Note: Code Mode execution variables (codeExecActive, activeCodeExecId, codeExecState, codeExecPollInterval)
  // are declared earlier in buildUi before the codeModeView creation

  // Phase icons for progress visualization
  const PHASE_ICONS: Record<string, string> = {
    'pending': '⏳',
    'intent': '🎯',
    'contract': '📋',
    'decompose': '🔧',
    'build': '🔨',
    'verify': '✓',
    'debug': '🔧',
    'exploring': '🔀',
    'integrate': '📦',
    'gap': '🔍',
    'completed': '✅',
    'failed': '❌',
    'approval': '⏸️',
  };

  // Render execution state in the Code Mode view (replaces old inspector)
  function renderCodeExecutionInspector() {
    codeModeView.updateExecutionState(codeExecState);
  }

  function startCodeExecPolling(executionId: string) {
    activeCodeExecId = executionId;
    codeExecActive = true;
    playInspectorActive = false;

    // Show immediate "Starting Execution" state before first poll
    codeExecState = {
      execution_id: executionId,
      status: 'pending',
      phase_index: 0,
      phase_description: 'Starting execution...',
      is_complete: false,
      success: false,
      steps_completed: 0,
      steps_total: 0,
      iteration: 0,
      max_iterations: 10,
      elapsed_seconds: 0,
      output_lines: ['Initializing execution...'],
      files_changed: [],
      current_step: null,
      debug_diagnosis: null,
      debug_attempt: 0,
      is_exploring: false,
      exploration_alternatives_total: 0,
      exploration_current_idx: 0,
      exploration_current_alternative: null,
      exploration_results: [],
      result_message: null,
      error: null,
    };
    renderCodeExecutionInspector();

    // Poll every 500ms
    codeExecPollInterval = setInterval(() => {
      void (async () => {
        try {
          const state = await kernelRequest('code/exec/state', { execution_id: executionId }) as CodeExecutionState;
          codeExecState = state;
          renderCodeExecutionInspector();

          // Stop polling when complete
          if (state.is_complete) {
            stopCodeExecPolling();
          }
        } catch (e) {
          console.error('Code exec poll error:', e);
          // Show error state in Code Mode view
          if (codeExecState) {
            codeExecState = {
              ...codeExecState,
              is_complete: true,
              success: false,
              error: `Lost connection to execution: ${e instanceof Error ? e.message : String(e)}`,
            };
            renderCodeExecutionInspector();
          }
          stopCodeExecPolling();
        }
      })();
    }, 500);
  }

  function stopCodeExecPolling() {
    if (codeExecPollInterval) {
      clearInterval(codeExecPollInterval);
      codeExecPollInterval = null;
    }
    // Keep codeExecActive true so view stays visible
  }

  // Log JSON to console for debugging (no longer renders to inspector)
  function showJsonInInspector(title: string, obj: unknown) {
    console.log(`[${title}]`, obj);
  }

  async function openDashboardWindow() {
    console.log('openDashboardWindow called');
    try {
      const existing = await WebviewWindow.getByLabel('dashboard');
      console.log('existing dashboard window:', existing);
      if (existing) {
        await existing.setFocus();
        return;
      }
    } catch (e) {
      console.log('getByLabel error (expected if window does not exist):', e);
      // Best effort: if getByLabel fails, fall through and create a new window.
    }

    try {
      console.log('Creating new dashboard window...');
      const w = new WebviewWindow('dashboard', {
        title: 'System Dashboard — Talking Rock',
        url: '/?view=dashboard',
        width: 1000,
        height: 800
      });
      console.log('WebviewWindow created:', w);

      w.once('tauri://created', () => {
        console.log('Dashboard window created successfully');
      });
      w.once('tauri://error', (e) => {
        console.error('Dashboard window creation error:', e);
      });
    } catch (e) {
      console.error('Failed to create dashboard window:', e);
    }
  }

  async function openPlayWindow() {
    console.log('openPlayWindow called');
    try {
      const existing = await WebviewWindow.getByLabel('play');
      console.log('existing play window:', existing);
      if (existing) {
        await existing.setFocus();
        return;
      }
    } catch (e) {
      console.log('getByLabel error (expected if window does not exist):', e);
      // Best effort: if getByLabel fails, fall through and create a new window.
    }

    try {
      console.log('Creating new play window...');
      const w = new WebviewWindow('play', {
        title: 'The Play — Talking Rock',
        url: '/?view=play',
        width: 1920,
        height: 1080,
      });
      console.log('WebviewWindow created:', w);

      w.once('tauri://created', () => {
        console.log('Play window created successfully');
      });
      w.once('tauri://error', (e) => {
        console.error('Play window creation error:', e);
      });
    } catch (e) {
      console.error('Failed to create play window:', e);
    }
  }

  // Play button opens The Play window (standalone 1080p window)
  playBtn.addEventListener('click', () => void openPlayWindow());
  dashboardBtn.addEventListener('click', () => void openDashboardWindow());

  // Helper functions (rowHeader, label, textInput, textArea, smallButton)
  // are now imported from ./dom.ts

  async function refreshBeats(actId: string, sceneId: string) {
    const res = (await kernelRequest('play/beats/list', { act_id: actId, scene_id: sceneId })) as PlayBeatsListResult;
    beatsCache = res.beats ?? [];
  }

  async function refreshKbForSelection() {
    if (!activeActId) return;
    const sceneId = selectedSceneId ?? undefined;
    const beatId = selectedBeatId ?? undefined;

    const filesRes = (await kernelRequest('play/kb/list', {
      act_id: activeActId,
      scene_id: sceneId,
      beat_id: beatId
    })) as PlayKbListResult;

    const files = filesRes.files ?? [];
    if (files.length > 0 && !files.includes(kbSelectedPath)) {
      kbSelectedPath = files[0];
    }

    try {
      const readRes = (await kernelRequest('play/kb/read', {
        act_id: activeActId,
        scene_id: sceneId,
        beat_id: beatId,
        path: kbSelectedPath
      })) as PlayKbReadResult;
      kbTextDraft = readRes.text ?? '';
    } catch {
      // If missing, keep draft as-is (acts as a create).
    }
    kbPreview = null;
  }

  function renderPlayInspector() {
    inspectionTitle.textContent = 'The Play';
    inspectionBody.innerHTML = '';

    if (!activeActId) {
      const empty = el('div');
      empty.textContent = 'Create an Act to begin.';
      empty.style.opacity = '0.8';
      inspectionBody.appendChild(empty);

      inspectionBody.appendChild(rowHeader('Act'));
      const actCreateRow = el('div');
      actCreateRow.style.display = 'flex';
      actCreateRow.style.gap = '8px';
      const actNewTitle = textInput('');
      actNewTitle.placeholder = 'New act title';
      const actCreate = smallButton('Create');
      actCreateRow.appendChild(actNewTitle);
      actCreateRow.appendChild(actCreate);
      inspectionBody.appendChild(actCreateRow);

      actCreate.addEventListener('click', () => {
        void (async () => {
          const title = actNewTitle.value.trim();
          if (!title) return;
          const res = (await kernelRequest('play/acts/create', { title })) as PlayActsCreateResult;
          activeActId = res.created_act_id;
          selectedSceneId = null;
          selectedBeatId = null;
          await refreshActs();
          if (activeActId) await refreshScenes(activeActId);
        })();
      });
      return;
    }

    const activeAct = actsCache.find((a) => a.act_id === activeActId) ?? null;

    const status = el('div');
    status.style.fontSize = '12px';
    status.style.opacity = '0.85';
    status.style.marginBottom = '8px';
    status.textContent = selectedBeatId
      ? `Act → Scene → Beat`
      : selectedSceneId
        ? `Act → Scene`
        : `Act`;
    inspectionBody.appendChild(status);

    // Act editor + create
    inspectionBody.appendChild(rowHeader('Act'));

    const actTitle = textInput('');
    const actNotes = textArea('', 70);
    const actRepoPath = textInput('');
    actRepoPath.placeholder = '/path/to/project';
    actRepoPath.style.flex = '1';
    const actRepoRow = el('div');
    actRepoRow.style.display = 'flex';
    actRepoRow.style.gap = '8px';
    actRepoRow.style.alignItems = 'center';
    actRepoRow.style.flexWrap = 'wrap';

    // Browse button for folder picker
    const actRepoBrowse = smallButton('Browse...');
    actRepoBrowse.style.background = 'rgba(59, 130, 246, 0.3)';
    actRepoBrowse.style.borderColor = '#3b82f6';
    actRepoBrowse.style.color = '#60a5fa';

    const actRepoOrLabel = el('span');
    actRepoOrLabel.textContent = 'or';
    actRepoOrLabel.style.color = 'rgba(255, 255, 255, 0.4)';
    actRepoOrLabel.style.fontSize = '11px';

    const actRepoAssign = smallButton('Set');
    actRepoRow.appendChild(actRepoBrowse);
    actRepoRow.appendChild(actRepoOrLabel);
    actRepoRow.appendChild(actRepoPath);
    actRepoRow.appendChild(actRepoAssign);
    const actRepoStatus = el('div');
    actRepoStatus.style.fontSize = '11px';
    actRepoStatus.style.marginTop = '4px';
    actRepoStatus.style.color = '#666';
    const actSave = smallButton('Save Act');
    const actCreateRow = el('div');
    actCreateRow.style.display = 'flex';
    actCreateRow.style.gap = '8px';
    const actNewTitle = textInput('');
    actNewTitle.placeholder = 'New act title';
    const actCreate = smallButton('Create');
    actCreateRow.appendChild(actNewTitle);
    actCreateRow.appendChild(actCreate);

    inspectionBody.appendChild(label('Title'));
    inspectionBody.appendChild(actTitle);
    inspectionBody.appendChild(label('Notes'));
    inspectionBody.appendChild(actNotes);
    inspectionBody.appendChild(label('Repository Path'));
    inspectionBody.appendChild(actRepoRow);
    inspectionBody.appendChild(actRepoStatus);
    inspectionBody.appendChild(actSave);
    inspectionBody.appendChild(label('Create new act'));
    inspectionBody.appendChild(actCreateRow);

    void (async () => {
      if (!activeAct) return;
      actTitle.value = activeAct.title ?? '';
      actNotes.value = activeAct.notes ?? '';
      actRepoPath.value = activeAct.repo_path ?? '';
      if (activeAct.repo_path) {
        actRepoStatus.textContent = `Current: ${activeAct.repo_path}`;
        actRepoStatus.style.color = '#22c55e';
      } else {
        actRepoStatus.textContent = 'No repository assigned. Code mode requires a repo.';
        actRepoStatus.style.color = '#f59e0b';
      }
    })();

    actSave.addEventListener('click', () => {
      void (async () => {
        if (!activeActId) return;
        await kernelRequest('play/acts/update', {
          act_id: activeActId,
          title: actTitle.value,
          notes: actNotes.value
        });
        await refreshActs();
      })();
    });

    // Helper to assign repo path
    const assignActRepo = async (repoPath: string) => {
      if (!activeActId) return;
      if (!repoPath) {
        actRepoStatus.textContent = 'Please select or enter a path';
        actRepoStatus.style.color = '#ef4444';
        return;
      }
      try {
        actRepoStatus.textContent = 'Setting...';
        actRepoStatus.style.color = '#60a5fa';
        const res = await kernelRequest('play/acts/assign_repo', {
          act_id: activeActId,
          repo_path: repoPath,
        }) as { success: boolean; repo_path: string };
        actRepoStatus.textContent = `Set: ${res.repo_path}`;
        actRepoStatus.style.color = '#22c55e';
        actRepoPath.value = res.repo_path;
        await refreshActs();
      } catch (err) {
        actRepoStatus.textContent = `Error: ${String(err)}`;
        actRepoStatus.style.color = '#ef4444';
      }
    };

    // Browse button - opens folder picker
    actRepoBrowse.addEventListener('click', () => {
      void (async () => {
        try {
          const selected = await openDialog({
            directory: true,
            multiple: false,
            title: 'Select Repository Folder',
          });
          if (selected && typeof selected === 'string') {
            actRepoPath.value = selected;  // Update text field immediately
            await assignActRepo(selected);
          }
        } catch (err) {
          actRepoStatus.textContent = `Error: ${String(err)}`;
          actRepoStatus.style.color = '#ef4444';
        }
      })();
    });

    // Manual text entry
    actRepoAssign.addEventListener('click', () => {
      void (async () => {
        await assignActRepo(actRepoPath.value.trim());
      })();
    });

    actCreate.addEventListener('click', () => {
      void (async () => {
        const title = actNewTitle.value.trim();
        if (!title) return;
        const res = (await kernelRequest('play/acts/create', { title })) as PlayActsCreateResult;
        activeActId = res.created_act_id;
        selectedSceneId = null;
        selectedBeatId = null;
        await refreshActs();
        if (activeActId) await refreshScenes(activeActId);
      })();
    });

    // Scenes section
    inspectionBody.appendChild(rowHeader('Scenes'));

    const sceneCreateTitle = textInput('');
    sceneCreateTitle.placeholder = 'New scene title';
    const sceneCreateBtn = smallButton('Create');
    const sceneCreateRow = el('div');
    sceneCreateRow.style.display = 'flex';
    sceneCreateRow.style.gap = '8px';
    sceneCreateRow.appendChild(sceneCreateTitle);
    sceneCreateRow.appendChild(sceneCreateBtn);
    inspectionBody.appendChild(sceneCreateRow);

    const scenesList = el('div');
    scenesList.style.display = 'flex';
    scenesList.style.flexDirection = 'column';
    scenesList.style.gap = '6px';
    scenesList.style.marginTop = '8px';
    inspectionBody.appendChild(scenesList);

    const sceneDetails = el('div');
    inspectionBody.appendChild(sceneDetails);

    const beatsDetails = el('div');
    inspectionBody.appendChild(beatsDetails);

    const kbSection = el('div');
    inspectionBody.appendChild(kbSection);

    const renderScenesList = () => {
      scenesList.innerHTML = '';
      if (scenesCache.length === 0) {
        const empty = el('div');
        empty.textContent = '(no scenes yet)';
        empty.style.opacity = '0.7';
        scenesList.appendChild(empty);
        return;
      }
      for (const s of scenesCache) {
        const btn = smallButton(selectedSceneId === s.scene_id ? `• ${s.title}` : s.title);
        btn.style.textAlign = 'left';
        btn.addEventListener('click', () => {
          selectedSceneId = s.scene_id;
          selectedBeatId = null;
          void (async () => {
            if (activeActId) {
              await refreshBeats(activeActId, s.scene_id);
              await refreshKbForSelection();
            }
            renderPlayInspector();
          })();
        });
        scenesList.appendChild(btn);
      }
    };

    const renderSceneDetails = () => {
      sceneDetails.innerHTML = '';
      if (!selectedSceneId) return;
      const s = scenesCache.find((x) => x.scene_id === selectedSceneId);
      if (!s) return;

      sceneDetails.appendChild(rowHeader('Scene Details'));
      const tTitle = textInput(s.title ?? '');
      const tIntent = textInput(s.intent ?? '');
      const tStatus = textInput(s.status ?? '');
      const tH = textInput(s.time_horizon ?? '');
      const tNotes = textArea(s.notes ?? '', 80);
      const save = smallButton('Save Scene');

      sceneDetails.appendChild(label('Title'));
      sceneDetails.appendChild(tTitle);
      sceneDetails.appendChild(label('Intent'));
      sceneDetails.appendChild(tIntent);
      sceneDetails.appendChild(label('Status'));
      sceneDetails.appendChild(tStatus);
      sceneDetails.appendChild(label('Time horizon'));
      sceneDetails.appendChild(tH);
      sceneDetails.appendChild(label('Notes'));
      sceneDetails.appendChild(tNotes);
      sceneDetails.appendChild(save);

      save.addEventListener('click', () => {
        void (async () => {
          if (!activeActId || !selectedSceneId) return;
          await kernelRequest('play/scenes/update', {
            act_id: activeActId,
            scene_id: selectedSceneId,
            title: tTitle.value,
            intent: tIntent.value,
            status: tStatus.value,
            time_horizon: tH.value,
            notes: tNotes.value
          });
          await refreshScenes(activeActId);
          renderPlayInspector();
        })();
      });
    };

    const renderBeats = () => {
      beatsDetails.innerHTML = '';
      if (!activeActId || !selectedSceneId) return;

      beatsDetails.appendChild(rowHeader('Beats'));

      const createRow = el('div');
      createRow.style.display = 'flex';
      createRow.style.gap = '8px';
      const newTitle = textInput('');
      newTitle.placeholder = 'New beat title';
      const newStatus = textInput('');
      newStatus.placeholder = 'status';
      const createBtn = smallButton('Create');
      createRow.appendChild(newTitle);
      createRow.appendChild(newStatus);
      createRow.appendChild(createBtn);
      beatsDetails.appendChild(createRow);

      const list = el('div');
      list.style.display = 'flex';
      list.style.flexDirection = 'column';
      list.style.gap = '6px';
      list.style.marginTop = '8px';
      beatsDetails.appendChild(list);

      const detail = el('div');
      beatsDetails.appendChild(detail);

      const renderList = () => {
        list.innerHTML = '';
        if (beatsCache.length === 0) {
          const empty = el('div');
          empty.textContent = '(no beats yet)';
          empty.style.opacity = '0.7';
          list.appendChild(empty);
          return;
        }
        for (const b of beatsCache) {
          const btn = smallButton(selectedBeatId === b.beat_id ? `• ${b.title}` : b.title);
          btn.style.textAlign = 'left';
          btn.addEventListener('click', () => {
            selectedBeatId = b.beat_id;
            void (async () => {
              await refreshKbForSelection();
              renderPlayInspector();
            })();
          });
          list.appendChild(btn);
        }
      };

      const renderDetail = () => {
        detail.innerHTML = '';
        if (!selectedBeatId) return;
        const b = beatsCache.find((x) => x.beat_id === selectedBeatId);
        if (!b) return;

        detail.appendChild(rowHeader('Beat Details'));
        const tTitle = textInput(b.title ?? '');
        const tStage = textInput(b.stage ?? '');
        const tLink = textInput(b.link ?? '');
        const tNotes = textArea(b.notes ?? '', 80);
        const save = smallButton('Save Beat');

        detail.appendChild(label('Title'));
        detail.appendChild(tTitle);
        detail.appendChild(label('Stage'));
        detail.appendChild(tStage);
        detail.appendChild(label('Link'));
        detail.appendChild(tLink);
        detail.appendChild(label('Notes'));
        detail.appendChild(tNotes);
        detail.appendChild(save);

        save.addEventListener('click', () => {
          void (async () => {
            if (!activeActId || !selectedSceneId || !selectedBeatId) return;
            await kernelRequest('play/beats/update', {
              act_id: activeActId,
              scene_id: selectedSceneId,
              beat_id: selectedBeatId,
              title: tTitle.value,
              stage: tStage.value,
              link: tLink.value || null,
              notes: tNotes.value
            });
            await refreshBeats(activeActId, selectedSceneId);
            void refreshAttentionItems();  // Refresh attention items after beat update
            renderPlayInspector();
          })();
        });
      };

      createBtn.addEventListener('click', () => {
        void (async () => {
          const title = newTitle.value.trim();
          if (!title) return;
          if (!activeActId || !selectedSceneId) return;
          await kernelRequest('play/beats/create', {
            act_id: activeActId,
            scene_id: selectedSceneId,
            title,
            status: newStatus.value
          });
          await refreshBeats(activeActId, selectedSceneId);
          void refreshAttentionItems();  // Refresh attention items after beat create
          renderPlayInspector();
        })();
      });

      renderList();
      renderDetail();
    };

    const renderKb = () => {
      kbSection.innerHTML = '';
      kbSection.appendChild(rowHeader('Mini Knowledgebase'));

      const who = el('div');
      who.style.fontSize = '12px';
      who.style.opacity = '0.8';
      who.style.marginBottom = '6px';
      who.textContent = selectedBeatId
        ? `Beat KB`
        : selectedSceneId
          ? `Scene KB`
          : `Act KB`;
      kbSection.appendChild(who);

      const fileRow = el('div');
      fileRow.style.display = 'flex';
      fileRow.style.gap = '8px';
      const pathInput = textInput(kbSelectedPath);
      const loadBtn = smallButton('Load');
      fileRow.appendChild(pathInput);
      fileRow.appendChild(loadBtn);
      kbSection.appendChild(fileRow);

      const listWrap = el('div');
      listWrap.style.display = 'flex';
      listWrap.style.flexWrap = 'wrap';
      listWrap.style.gap = '6px';
      listWrap.style.margin = '8px 0';
      kbSection.appendChild(listWrap);

      const editor = textArea(kbTextDraft, 180);
      kbSection.appendChild(editor);

      const btnRow = el('div');
      btnRow.style.display = 'flex';
      btnRow.style.gap = '8px';
      btnRow.style.marginTop = '8px';
      const previewBtn = smallButton('Preview');
      const applyBtn = smallButton('Apply');
      btnRow.appendChild(previewBtn);
      btnRow.appendChild(applyBtn);
      kbSection.appendChild(btnRow);

      const diffPre = el('pre');
      diffPre.style.whiteSpace = 'pre-wrap';
      diffPre.style.fontSize = '12px';
      diffPre.style.marginTop = '8px';
      diffPre.style.padding = '8px 10px';
      diffPre.style.borderRadius = '10px';
      diffPre.style.border = '1px solid rgba(209, 213, 219, 0.65)';
      diffPre.style.background = 'rgba(255, 255, 255, 0.35)';
      diffPre.textContent = kbPreview ? kbPreview.diff : '';
      kbSection.appendChild(diffPre);

      const errorLine = el('div');
      errorLine.style.fontSize = '12px';
      errorLine.style.marginTop = '6px';
      errorLine.style.opacity = '0.85';
      kbSection.appendChild(errorLine);

      editor.addEventListener('input', () => {
        kbTextDraft = editor.value;
      });

      pathInput.addEventListener('input', () => {
        kbSelectedPath = pathInput.value;
      });

      loadBtn.addEventListener('click', () => {
        void (async () => {
          errorLine.textContent = '';
          kbSelectedPath = pathInput.value || 'kb.md';
          await refreshKbForSelection();
          renderPlayInspector();
        })();
      });

      previewBtn.addEventListener('click', () => {
        void (async () => {
          errorLine.textContent = '';
          if (!activeActId) return;
          try {
            const res = (await kernelRequest('play/kb/write_preview', {
              act_id: activeActId,
              scene_id: selectedSceneId,
              beat_id: selectedBeatId,
              path: kbSelectedPath,
              text: editor.value
            })) as PlayKbWritePreviewResult;
            kbPreview = res;
            diffPre.textContent = res.diff ?? '';
          } catch (e) {
            errorLine.textContent = `Preview error: ${String(e)}`;
          }
        })();
      });

      applyBtn.addEventListener('click', () => {
        void (async () => {
          errorLine.textContent = '';
          if (!activeActId) return;
          if (!kbPreview) {
            errorLine.textContent = 'Preview first.';
            return;
          }
          try {
            const res = (await kernelRequest('play/kb/write_apply', {
              act_id: activeActId,
              scene_id: selectedSceneId,
              beat_id: selectedBeatId,
              path: kbSelectedPath,
              text: editor.value,
              expected_sha256_current: kbPreview.expected_sha256_current
            })) as PlayKbWriteApplyResult;
            void res;
            await refreshKbForSelection();
            renderPlayInspector();
          } catch (e) {
            if (e instanceof KernelError && e.code === -32009) {
              errorLine.textContent = 'Conflict: file changed since preview. Re-preview to continue.';
            } else {
              errorLine.textContent = `Apply error: ${String(e)}`;
            }
          }
        })();
      });

      // Render file pills if we already have them cached.
      void (async () => {
        try {
          if (!activeActId) return;
          const filesRes = (await kernelRequest('play/kb/list', {
            act_id: activeActId,
            scene_id: selectedSceneId,
            beat_id: selectedBeatId
          })) as PlayKbListResult;
          const files = filesRes.files ?? [];
          listWrap.innerHTML = '';
          for (const f of files) {
            const pill = smallButton(f);
            pill.addEventListener('click', () => {
              kbSelectedPath = f;
              void (async () => {
                await refreshKbForSelection();
                renderPlayInspector();
              })();
            });
            listWrap.appendChild(pill);
          }
        } catch {
          // ignore
        }
      })();
    };

    sceneCreateBtn.addEventListener('click', () => {
      void (async () => {
        const title = sceneCreateTitle.value.trim();
        if (!title || !activeActId) return;
        await kernelRequest('play/scenes/create', { act_id: activeActId, title });
        await refreshScenes(activeActId);
        renderPlayInspector();
      })();
    });

    renderScenesList();
    renderSceneDetails();
    renderBeats();
    void (async () => {
      await refreshKbForSelection();
      renderKb();
    })();
  }

  async function refreshActs() {
    const res = (await kernelRequest('play/acts/list', {})) as PlayActsListResult;
    activeActId = res.active_act_id ?? null;
    actsCache = res.acts ?? [];

    // Only render The Play inspector if the user has activated it
    if (playInspectorActive) {
      renderPlayInspector();
    }
  }

  async function refreshScenes(actId: string) {
    const res = (await kernelRequest('play/scenes/list', { act_id: actId })) as PlayScenesListResult;
    scenesCache = res.scenes ?? [];
    if (selectedSceneId && !scenesCache.some((s) => s.scene_id === selectedSceneId)) {
      selectedSceneId = null;
      selectedBeatId = null;
    }
    if (activeActId) {
      if (selectedSceneId) {
        await refreshBeats(activeActId, selectedSceneId);
      } else {
        beatsCache = [];
      }
    }
    // Only render The Play inspector if the user has activated it
    if (playInspectorActive) {
      renderPlayInspector();
    }
  }


  // Note: currentConversationId is declared earlier in buildUi

  // Legacy stub for context meter click (not visible in new UI)
  const contextMeter = el('div');
  contextMeter.addEventListener('click', () => {
    contextOverlay.show(currentConversationId);
  });

  // --- Context Meter & Chat Actions ---

  async function updateContextMeter() {
    try {
      const stats = await kernelRequest('context/stats', {
        conversation_id: currentConversationId,
      }) as ContextStatsResult;

      // Update progress bar
      meterFill.style.width = `${Math.min(100, stats.usage_percent)}%`;
      meterText.textContent = `${Math.round(stats.usage_percent)}%`;

      // Color based on warning level
      if (stats.warning_level === 'critical') {
        meterFill.style.background = '#ef4444';
        meterText.style.color = '#ef4444';
      } else if (stats.warning_level === 'warning') {
        meterFill.style.background = '#f59e0b';
        meterText.style.color = '#f59e0b';
      } else {
        meterFill.style.background = '#22c55e';
        meterText.style.color = 'inherit';
      }
    } catch (e) {
      console.error('Failed to update context meter:', e);
    }
  }

  // Update context meter periodically and after messages
  setInterval(() => void updateContextMeter(), 30000);

  // Helper to render command preview with approve/reject buttons
  function appendCommandPreview(
    approval: ApprovalPendingResult['approvals'][0],
    container: HTMLElement
  ) {
    const previewBox = el('div');
    previewBox.className = 'command-preview';
    previewBox.style.margin = '8px 0';
    previewBox.style.padding = '12px';
    previewBox.style.background = 'rgba(0, 0, 0, 0.03)';
    previewBox.style.border = '1px solid #e5e7eb';
    previewBox.style.borderRadius = '8px';

    // Risk level indicator
    const riskColors: Record<string, string> = {
      safe: '#22c55e',
      low: '#84cc16',
      medium: '#f59e0b',
      high: '#ef4444',
      critical: '#dc2626'
    };
    const riskColor = riskColors[approval.risk_level] ?? '#6b7280';

    const header = el('div');
    header.style.display = 'flex';
    header.style.alignItems = 'center';
    header.style.gap = '8px';
    header.style.marginBottom = '8px';

    const riskBadge = el('span');
    riskBadge.textContent = approval.risk_level.toUpperCase();
    riskBadge.style.padding = '2px 8px';
    riskBadge.style.background = riskColor;
    riskBadge.style.color = 'white';
    riskBadge.style.borderRadius = '4px';
    riskBadge.style.fontSize = '11px';
    riskBadge.style.fontWeight = '600';

    const title = el('span');
    title.textContent = 'Command Preview';
    title.style.fontWeight = '600';
    title.style.fontSize = '13px';

    header.appendChild(riskBadge);
    header.appendChild(title);

    // Command display
    const commandBox = el('div');
    commandBox.style.fontFamily = 'monospace';
    commandBox.style.background = '#1e1e1e';
    commandBox.style.color = '#d4d4d4';
    commandBox.style.padding = '8px';
    commandBox.style.borderRadius = '4px';
    commandBox.style.marginBottom = '8px';
    commandBox.style.fontSize = '13px';
    commandBox.style.overflow = 'auto';
    commandBox.textContent = approval.command;

    // Explanation
    const explanation = el('div');
    explanation.style.fontSize = '12px';
    explanation.style.opacity = '0.8';
    explanation.style.marginBottom = '12px';
    explanation.textContent = approval.explanation ?? 'No explanation available.';

    // Edit command section (hidden by default)
    const editSection = el('div');
    editSection.style.display = 'none';
    editSection.style.marginBottom = '12px';

    const editInput = el('textarea');
    editInput.value = approval.command;
    editInput.style.width = '100%';
    editInput.style.fontFamily = 'monospace';
    editInput.style.fontSize = '12px';
    editInput.style.padding = '8px';
    editInput.style.border = '1px solid #e5e7eb';
    editInput.style.borderRadius = '4px';
    editInput.style.resize = 'vertical';
    editInput.style.minHeight = '60px';
    editInput.style.background = '#1e1e1e';
    editInput.style.color = '#d4d4d4';

    const editButtons = el('div');
    editButtons.style.display = 'flex';
    editButtons.style.gap = '8px';
    editButtons.style.marginTop = '8px';

    const saveEditBtn = smallButton('Save & Approve');
    saveEditBtn.style.background = '#22c55e';
    saveEditBtn.style.color = 'white';
    saveEditBtn.style.border = 'none';

    const cancelEditBtn = smallButton('Cancel');

    editButtons.appendChild(saveEditBtn);
    editButtons.appendChild(cancelEditBtn);
    editSection.appendChild(editInput);
    editSection.appendChild(editButtons);

    // Buttons row
    const buttons = el('div');
    buttons.style.display = 'flex';
    buttons.style.gap = '8px';

    const approveBtn = smallButton('Approve');
    approveBtn.style.background = '#22c55e';
    approveBtn.style.color = 'white';
    approveBtn.style.border = 'none';

    const editBtn = smallButton('Edit');
    editBtn.style.background = '#3b82f6';
    editBtn.style.color = 'white';
    editBtn.style.border = 'none';

    const rejectBtn = smallButton('Reject');
    rejectBtn.style.background = '#ef4444';
    rejectBtn.style.color = 'white';
    rejectBtn.style.border = 'none';

    const explainBtn = smallButton('Explain More');

    // Streaming output container
    const streamingOutput = el('div');
    streamingOutput.className = 'streaming-output';
    streamingOutput.style.display = 'none';
    streamingOutput.style.marginTop = '12px';
    streamingOutput.style.background = '#1e1e1e';
    streamingOutput.style.borderRadius = '4px';
    streamingOutput.style.padding = '8px';
    streamingOutput.style.maxHeight = '200px';
    streamingOutput.style.overflow = 'auto';
    streamingOutput.style.fontFamily = 'monospace';
    streamingOutput.style.fontSize = '12px';
    streamingOutput.style.color = '#d4d4d4';

    // Execute with streaming output
    async function executeWithStreaming(command: string, edited: boolean) {
      approveBtn.disabled = true;
      editBtn.disabled = true;
      rejectBtn.disabled = true;
      explainBtn.disabled = true;
      approveBtn.textContent = 'Executing...';

      // Show streaming output
      streamingOutput.style.display = 'block';
      streamingOutput.innerHTML = '<span style="opacity: 0.6">Starting...</span>';

      try {
        // Use approval/respond which handles the execution
        const result = await kernelRequest('approval/respond', {
          approval_id: approval.id,
          action: 'approve',
          edited_command: edited ? command : undefined
        }) as ApprovalRespondResult;

        // Update streaming output with result
        streamingOutput.innerHTML = '';

        if (result.status === 'executed' && result.result?.success) {
          const successHeader = el('div');
          successHeader.innerHTML = '<strong style="color: #22c55e;">✓ Command executed successfully</strong>';
          streamingOutput.appendChild(successHeader);

          if (result.result?.stdout) {
            const output = el('pre');
            output.style.margin = '8px 0 0';
            output.style.whiteSpace = 'pre-wrap';
            output.style.wordBreak = 'break-word';
            output.textContent = result.result.stdout;
            streamingOutput.appendChild(output);
          }
          streamingOutput.style.borderLeft = '3px solid #22c55e';
        } else {
          const errorHeader = el('div');
          errorHeader.innerHTML = '<strong style="color: #ef4444;">✗ Command failed</strong>';
          streamingOutput.appendChild(errorHeader);

          if (result.result?.stderr || result.result?.error) {
            const output = el('pre');
            output.style.margin = '8px 0 0';
            output.style.whiteSpace = 'pre-wrap';
            output.style.wordBreak = 'break-word';
            output.style.color = '#ef4444';
            output.textContent = result.result.stderr ?? result.result.error ?? '';
            streamingOutput.appendChild(output);
          }
          streamingOutput.style.borderLeft = '3px solid #ef4444';
        }

        // Hide buttons after execution
        buttons.style.display = 'none';
        editSection.style.display = 'none';
      } catch (e) {
        streamingOutput.innerHTML = `<strong style="color: #ef4444;">Error: ${String(e)}</strong>`;
        streamingOutput.style.borderLeft = '3px solid #ef4444';
        approveBtn.textContent = 'Approve';
        approveBtn.disabled = false;
        editBtn.disabled = false;
        rejectBtn.disabled = false;
        explainBtn.disabled = false;
      }
    }

    // Handle approve
    approveBtn.addEventListener('click', () => {
      void executeWithStreaming(approval.command, false);
    });

    // Handle edit
    editBtn.addEventListener('click', () => {
      editSection.style.display = 'block';
      commandBox.style.display = 'none';
      buttons.style.display = 'none';
    });

    cancelEditBtn.addEventListener('click', () => {
      editSection.style.display = 'none';
      commandBox.style.display = 'block';
      buttons.style.display = 'flex';
      editInput.value = approval.command;
    });

    saveEditBtn.addEventListener('click', () => {
      const editedCommand = editInput.value.trim();
      if (editedCommand) {
        commandBox.textContent = editedCommand;
        void executeWithStreaming(editedCommand, true);
      }
    });

    // Handle reject
    rejectBtn.addEventListener('click', async () => {
      try {
        await kernelRequest('approval/respond', {
          approval_id: approval.id,
          action: 'reject'
        });
        previewBox.innerHTML = '';
        const rejectedBox = el('div');
        rejectedBox.style.padding = '8px';
        rejectedBox.style.opacity = '0.6';
        rejectedBox.textContent = 'Command rejected.';
        previewBox.appendChild(rejectedBox);
      } catch (e) {
        console.error('Rejection error:', e);
        const errorBox = el('div');
        errorBox.style.cssText = 'padding: 8px; color: #ef4444; font-size: 12px;';
        errorBox.textContent = `Failed to reject: ${e instanceof Error ? e.message : String(e)}`;
        previewBox.appendChild(errorBox);
      }
    });

    // Handle explain
    explainBtn.addEventListener('click', async () => {
      try {
        const result = await kernelRequest('approval/explain', {
          approval_id: approval.id
        }) as ApprovalExplainResult;

        const existingExplain = previewBox.querySelector('.explain-box');
        if (existingExplain) existingExplain.remove();

        const explainBox = el('div');
        explainBox.className = 'explain-box';
        explainBox.style.marginTop = '12px';
        explainBox.style.padding = '12px';
        explainBox.style.background = 'rgba(59, 130, 246, 0.1)';
        explainBox.style.borderRadius = '4px';
        explainBox.style.fontSize = '12px';

        // Main explanation
        const mainExplain = el('div');
        mainExplain.innerHTML = `<pre style="margin: 0; white-space: pre-wrap;">${result.detailed_explanation}</pre>`;
        explainBox.appendChild(mainExplain);

        // Warnings (if any)
        if (result.warnings && result.warnings.length > 0) {
          const warningSection = el('div');
          warningSection.style.marginTop = '12px';
          warningSection.style.padding = '8px';
          warningSection.style.background = 'rgba(234, 179, 8, 0.2)';
          warningSection.style.borderRadius = '4px';
          warningSection.style.borderLeft = '3px solid #eab308';
          warningSection.innerHTML = '<strong style="color: #eab308;">⚠ Warnings:</strong>';
          const warningList = el('ul');
          warningList.style.margin = '4px 0 0 0';
          warningList.style.paddingLeft = '20px';
          for (const warn of result.warnings) {
            const li = el('li');
            li.textContent = warn;
            warningList.appendChild(li);
          }
          warningSection.appendChild(warningList);
          explainBox.appendChild(warningSection);
        }

        // Affected paths (if any)
        if (result.affected_paths && result.affected_paths.length > 0) {
          const pathsSection = el('div');
          pathsSection.style.marginTop = '12px';
          pathsSection.innerHTML = '<strong>📁 Affected paths:</strong>';
          const pathsList = el('ul');
          pathsList.style.margin = '4px 0 0 0';
          pathsList.style.paddingLeft = '20px';
          pathsList.style.fontFamily = 'monospace';
          pathsList.style.fontSize = '11px';
          for (const path of result.affected_paths.slice(0, 10)) {
            const li = el('li');
            li.textContent = path;
            pathsList.appendChild(li);
          }
          if (result.affected_paths.length > 10) {
            const li = el('li');
            li.style.opacity = '0.6';
            li.textContent = `... and ${result.affected_paths.length - 10} more`;
            pathsList.appendChild(li);
          }
          pathsSection.appendChild(pathsList);
          explainBox.appendChild(pathsSection);
        }

        // Undo command (if available)
        if (result.can_undo && result.undo_command) {
          const undoSection = el('div');
          undoSection.style.marginTop = '12px';
          undoSection.style.padding = '8px';
          undoSection.style.background = 'rgba(34, 197, 94, 0.1)';
          undoSection.style.borderRadius = '4px';
          undoSection.style.borderLeft = '3px solid #22c55e';
          undoSection.innerHTML = '<strong style="color: #22c55e;">↩ Can be undone with:</strong>';
          const undoCmd = el('pre');
          undoCmd.style.margin = '4px 0 0';
          undoCmd.style.fontFamily = 'monospace';
          undoCmd.style.fontSize = '11px';
          undoCmd.style.background = '#1e1e1e';
          undoCmd.style.color = '#d4d4d4';
          undoCmd.style.padding = '6px';
          undoCmd.style.borderRadius = '4px';
          undoCmd.textContent = result.undo_command;
          undoSection.appendChild(undoCmd);
          explainBox.appendChild(undoSection);
        } else if (result.is_destructive) {
          const noUndoSection = el('div');
          noUndoSection.style.marginTop = '12px';
          noUndoSection.style.padding = '8px';
          noUndoSection.style.background = 'rgba(239, 68, 68, 0.1)';
          noUndoSection.style.borderRadius = '4px';
          noUndoSection.style.borderLeft = '3px solid #ef4444';
          noUndoSection.innerHTML = '<strong style="color: #ef4444;">⚠ This operation cannot be undone</strong>';
          explainBox.appendChild(noUndoSection);
        }

        previewBox.appendChild(explainBox);
      } catch (e) {
        console.error('Explain error:', e);
        const errorBox = el('div');
        errorBox.style.cssText = 'padding: 8px; color: #ef4444; font-size: 12px;';
        errorBox.textContent = `Failed to explain: ${e instanceof Error ? e.message : String(e)}`;
        previewBox.appendChild(errorBox);
      }
    });

    buttons.appendChild(approveBtn);
    buttons.appendChild(editBtn);
    buttons.appendChild(rejectBtn);
    buttons.appendChild(explainBtn);

    previewBox.appendChild(header);
    previewBox.appendChild(commandBox);
    previewBox.appendChild(editSection);
    previewBox.appendChild(explanation);
    previewBox.appendChild(buttons);
    previewBox.appendChild(streamingOutput);

    container.appendChild(previewBox);
  }

  // Multi-step plan progress visualization
  function appendPlanProgress(
    plan: PlanPreviewResult,
    container: HTMLElement,
    onApprove: () => Promise<{ execution_id: string } | null>
  ) {
    if (!plan.steps || plan.steps.length === 0) return;

    const progressBox = el('div');
    progressBox.className = 'plan-progress';
    progressBox.style.margin = '8px 0';
    progressBox.style.padding = '12px';
    progressBox.style.background = 'rgba(0, 0, 0, 0.03)';
    progressBox.style.border = '1px solid #e5e7eb';
    progressBox.style.borderRadius = '8px';

    // Header with title and step count
    const header = el('div');
    header.style.display = 'flex';
    header.style.justifyContent = 'space-between';
    header.style.alignItems = 'center';
    header.style.marginBottom = '12px';

    const titleSection = el('div');
    const title = el('div');
    title.textContent = plan.title ?? 'Execution Plan';
    title.style.fontWeight = '600';
    title.style.fontSize = '14px';

    const stepCount = el('div');
    stepCount.textContent = `${plan.steps.length} steps`;
    stepCount.style.fontSize = '12px';
    stepCount.style.opacity = '0.7';

    titleSection.appendChild(title);
    titleSection.appendChild(stepCount);

    // Complexity badge
    const complexityBadge = el('span');
    const complexityColors: Record<string, string> = {
      simple: '#22c55e',
      complex: '#f59e0b',
      diagnostic: '#3b82f6',
      risky: '#ef4444'
    };
    complexityBadge.textContent = (plan.complexity ?? 'complex').toUpperCase();
    complexityBadge.style.padding = '2px 8px';
    complexityBadge.style.background = complexityColors[plan.complexity ?? 'complex'] ?? '#6b7280';
    complexityBadge.style.color = 'white';
    complexityBadge.style.borderRadius = '4px';
    complexityBadge.style.fontSize = '10px';
    complexityBadge.style.fontWeight = '600';

    header.appendChild(titleSection);
    header.appendChild(complexityBadge);

    // Overall progress bar
    const progressBarContainer = el('div');
    progressBarContainer.style.marginBottom = '16px';

    const progressLabel = el('div');
    progressLabel.className = 'progress-label';
    progressLabel.style.display = 'flex';
    progressLabel.style.justifyContent = 'space-between';
    progressLabel.style.fontSize = '11px';
    progressLabel.style.marginBottom = '4px';
    progressLabel.style.opacity = '0.8';
    progressLabel.innerHTML = '<span>Progress</span><span class="progress-text">0 / ' + plan.steps.length + '</span>';

    const progressTrack = el('div');
    progressTrack.style.height = '6px';
    progressTrack.style.background = '#e5e7eb';
    progressTrack.style.borderRadius = '3px';
    progressTrack.style.overflow = 'hidden';

    const progressFill = el('div');
    progressFill.className = 'progress-fill';
    progressFill.style.height = '100%';
    progressFill.style.width = '0%';
    progressFill.style.background = '#22c55e';
    progressFill.style.transition = 'width 0.3s ease';
    progressFill.style.borderRadius = '3px';

    progressTrack.appendChild(progressFill);
    progressBarContainer.appendChild(progressLabel);
    progressBarContainer.appendChild(progressTrack);

    // Steps list
    const stepsList = el('div');
    stepsList.className = 'steps-list';
    stepsList.style.display = 'flex';
    stepsList.style.flexDirection = 'column';
    stepsList.style.gap = '4px';

    interface StepState {
      status: 'pending' | 'running' | 'success' | 'failed';
      output: string;
    }
    const stepStates: Map<string, StepState> = new Map();

    for (const step of plan.steps) {
      stepStates.set(step.id, { status: 'pending', output: '' });

      const stepRow = el('div');
      stepRow.className = `step-row step-${step.id}`;
      stepRow.style.display = 'flex';
      stepRow.style.alignItems = 'flex-start';
      stepRow.style.gap = '8px';
      stepRow.style.padding = '8px';
      stepRow.style.background = 'rgba(255, 255, 255, 0.5)';
      stepRow.style.borderRadius = '4px';
      stepRow.style.cursor = 'pointer';
      stepRow.style.transition = 'background 0.2s';

      // Step number
      const stepNum = el('div');
      stepNum.className = 'step-number';
      stepNum.style.width = '24px';
      stepNum.style.height = '24px';
      stepNum.style.borderRadius = '50%';
      stepNum.style.background = '#e5e7eb';
      stepNum.style.display = 'flex';
      stepNum.style.alignItems = 'center';
      stepNum.style.justifyContent = 'center';
      stepNum.style.fontSize = '12px';
      stepNum.style.fontWeight = '600';
      stepNum.style.flexShrink = '0';
      stepNum.textContent = String(step.number);

      // Status icon
      const statusIcon = el('span');
      statusIcon.className = 'status-icon';
      statusIcon.style.marginRight = '4px';
      statusIcon.textContent = '○';

      // Step content
      const stepContent = el('div');
      stepContent.style.flex = '1';
      stepContent.style.minWidth = '0';

      const stepTitle = el('div');
      stepTitle.style.display = 'flex';
      stepTitle.style.alignItems = 'center';
      stepTitle.style.gap = '6px';

      const stepTitleText = el('span');
      stepTitleText.textContent = step.title;
      stepTitleText.style.fontWeight = '500';
      stepTitleText.style.fontSize = '13px';

      stepTitle.appendChild(statusIcon);
      stepTitle.appendChild(stepTitleText);

      // Risk indicator for this step
      if (step.risk?.level && step.risk.level !== 'safe') {
        const riskDot = el('span');
        riskDot.style.width = '6px';
        riskDot.style.height = '6px';
        riskDot.style.borderRadius = '50%';
        riskDot.style.background = step.risk.level === 'high' || step.risk.level === 'critical'
          ? '#ef4444'
          : step.risk.level === 'medium' ? '#f59e0b' : '#84cc16';
        riskDot.title = `Risk: ${step.risk.level}`;
        stepTitle.appendChild(riskDot);
      }

      // Command preview (collapsed by default)
      const stepDetails = el('div');
      stepDetails.className = 'step-details';
      stepDetails.style.display = 'none';
      stepDetails.style.marginTop = '8px';

      if (step.command) {
        const cmdBox = el('div');
        cmdBox.style.fontFamily = 'monospace';
        cmdBox.style.fontSize = '11px';
        cmdBox.style.background = '#1e1e1e';
        cmdBox.style.color = '#d4d4d4';
        cmdBox.style.padding = '6px';
        cmdBox.style.borderRadius = '4px';
        cmdBox.style.overflow = 'auto';
        cmdBox.textContent = step.command;
        stepDetails.appendChild(cmdBox);
      }

      // Output container (shown during/after execution)
      const outputBox = el('div');
      outputBox.className = 'step-output';
      outputBox.style.display = 'none';
      outputBox.style.marginTop = '6px';
      outputBox.style.fontFamily = 'monospace';
      outputBox.style.fontSize = '11px';
      outputBox.style.background = '#1e1e1e';
      outputBox.style.color = '#d4d4d4';
      outputBox.style.padding = '6px';
      outputBox.style.borderRadius = '4px';
      outputBox.style.maxHeight = '100px';
      outputBox.style.overflow = 'auto';
      outputBox.style.whiteSpace = 'pre-wrap';
      stepDetails.appendChild(outputBox);

      stepContent.appendChild(stepTitle);
      stepContent.appendChild(stepDetails);

      // Toggle details on click
      stepRow.addEventListener('click', () => {
        const isVisible = stepDetails.style.display !== 'none';
        stepDetails.style.display = isVisible ? 'none' : 'block';
        stepRow.style.background = isVisible ? 'rgba(255, 255, 255, 0.5)' : 'rgba(255, 255, 255, 0.8)';
      });

      stepRow.appendChild(stepNum);
      stepRow.appendChild(stepContent);
      stepsList.appendChild(stepRow);
    }

    // Control buttons
    const controls = el('div');
    controls.className = 'plan-controls';
    controls.style.display = 'flex';
    controls.style.gap = '8px';
    controls.style.marginTop = '16px';

    const approveBtn = smallButton('Execute Plan');
    approveBtn.style.background = '#22c55e';
    approveBtn.style.color = 'white';
    approveBtn.style.border = 'none';
    approveBtn.style.padding = '8px 16px';

    const rejectBtn = smallButton('Cancel');
    rejectBtn.style.background = '#ef4444';
    rejectBtn.style.color = 'white';
    rejectBtn.style.border = 'none';

    const abortBtn = smallButton('Abort');
    abortBtn.style.background = '#f59e0b';
    abortBtn.style.color = 'white';
    abortBtn.style.border = 'none';
    abortBtn.style.display = 'none';

    // Execution status
    const statusLine = el('div');
    statusLine.className = 'execution-status';
    statusLine.style.marginTop = '12px';
    statusLine.style.fontSize = '12px';
    statusLine.style.display = 'none';

    // Function to update step UI
    function updateStepUI(stepId: string, status: 'pending' | 'running' | 'success' | 'failed', output?: string) {
      const stepRow = stepsList.querySelector(`.step-${stepId}`) as HTMLElement;
      if (!stepRow) return;

      const statusIcon = stepRow.querySelector('.status-icon') as HTMLElement;
      const stepNum = stepRow.querySelector('.step-number') as HTMLElement;
      const outputBox = stepRow.querySelector('.step-output') as HTMLElement;
      const stepDetails = stepRow.querySelector('.step-details') as HTMLElement;

      // Update status icon and colors
      switch (status) {
        case 'pending':
          statusIcon.textContent = '○';
          statusIcon.style.color = '#9ca3af';
          stepNum.style.background = '#e5e7eb';
          break;
        case 'running':
          statusIcon.textContent = '⏳';
          statusIcon.style.color = '#f59e0b';
          stepNum.style.background = '#fef3c7';
          stepRow.style.background = 'rgba(254, 243, 199, 0.5)';
          // Auto-expand running step
          stepDetails.style.display = 'block';
          break;
        case 'success':
          statusIcon.textContent = '✓';
          statusIcon.style.color = '#22c55e';
          stepNum.style.background = '#dcfce7';
          stepRow.style.background = 'rgba(220, 252, 231, 0.5)';
          break;
        case 'failed':
          statusIcon.textContent = '✗';
          statusIcon.style.color = '#ef4444';
          stepNum.style.background = '#fee2e2';
          stepRow.style.background = 'rgba(254, 226, 226, 0.5)';
          // Auto-expand failed step
          stepDetails.style.display = 'block';
          break;
      }

      // Update output
      if (output && outputBox) {
        outputBox.style.display = 'block';
        outputBox.textContent = output;
        if (status === 'failed') {
          outputBox.style.borderLeft = '3px solid #ef4444';
        } else if (status === 'success') {
          outputBox.style.borderLeft = '3px solid #22c55e';
        }
      }

      // Update state
      stepStates.set(stepId, { status, output: output ?? '' });
    }

    // Function to update progress bar
    function updateProgress(completed: number, total: number, failed?: boolean) {
      const percent = Math.round((completed / total) * 100);
      progressFill.style.width = `${percent}%`;
      if (failed) {
        progressFill.style.background = '#ef4444';
      }
      const progressText = progressLabel.querySelector('.progress-text');
      if (progressText) {
        progressText.textContent = `${completed} / ${total}`;
      }
    }

    // Polling for execution status
    let pollInterval: ReturnType<typeof setInterval> | null = null;
    let executionId: string | null = null;

    async function startPolling(execId: string) {
      executionId = execId;
      let lastStep = -1;

      pollInterval = setInterval(async () => {
        try {
          const status = await kernelRequest('execution/status', {
            execution_id: execId
          }) as ExecutionStatusResult;

          // Update current step
          if (status.current_step !== lastStep && plan.steps) {
            lastStep = status.current_step;

            // Mark previous steps as complete, current as running
            for (let i = 0; i < plan.steps.length; i++) {
              const step = plan.steps[i];
              if (i < status.current_step) {
                const completed = status.completed_steps.find(s => s.step_id === step.id);
                updateStepUI(
                  step.id,
                  completed?.success ? 'success' : 'failed',
                  completed?.output_preview
                );
              } else if (i === status.current_step) {
                updateStepUI(step.id, 'running');
              }
            }
          }

          // Update progress
          updateProgress(status.completed_steps.length, status.total_steps);

          // Check if complete
          if (status.state === 'completed' || status.state === 'failed' || status.state === 'aborted') {
            if (pollInterval) {
              clearInterval(pollInterval);
              pollInterval = null;
            }

            // Final update
            abortBtn.style.display = 'none';

            if (status.state === 'completed') {
              statusLine.innerHTML = '<span style="color: #22c55e;">✓ Plan executed successfully</span>';
              // Mark all remaining as success
              for (const step of plan.steps ?? []) {
                const completed = status.completed_steps.find(s => s.step_id === step.id);
                if (completed) {
                  updateStepUI(step.id, completed.success ? 'success' : 'failed', completed.output_preview);
                }
              }
            } else if (status.state === 'failed') {
              statusLine.innerHTML = '<span style="color: #ef4444;">✗ Plan execution failed</span>';
              updateProgress(status.completed_steps.length, status.total_steps, true);
            } else if (status.state === 'aborted') {
              statusLine.innerHTML = '<span style="color: #f59e0b;">⚠ Plan execution aborted</span>';
            }
          }
        } catch (e) {
          console.error('Polling error:', e);
        }
      }, 500);
    }

    // Handle approve
    approveBtn.addEventListener('click', async () => {
      approveBtn.disabled = true;
      rejectBtn.style.display = 'none';
      approveBtn.textContent = 'Starting...';
      statusLine.style.display = 'block';
      statusLine.innerHTML = '<span style="opacity: 0.7;">Starting execution...</span>';

      try {
        const result = await onApprove();
        if (result?.execution_id) {
          approveBtn.style.display = 'none';
          abortBtn.style.display = 'inline-block';
          statusLine.innerHTML = '<span style="opacity: 0.7;">Executing...</span>';

          // Mark first step as running
          if (plan.steps && plan.steps.length > 0) {
            updateStepUI(plan.steps[0].id, 'running');
          }

          // Start Code Mode view polling for detailed execution state
          startCodeExecPolling(result.execution_id);

          await startPolling(result.execution_id);
        } else {
          approveBtn.textContent = 'Execute Plan';
          approveBtn.disabled = false;
          statusLine.innerHTML = '<span style="color: #ef4444;">Failed to start execution</span>';
        }
      } catch (e) {
        approveBtn.textContent = 'Execute Plan';
        approveBtn.disabled = false;
        statusLine.innerHTML = `<span style="color: #ef4444;">Error: ${String(e)}</span>`;
      }
    });

    // Handle reject/cancel
    rejectBtn.addEventListener('click', () => {
      progressBox.innerHTML = '';
      const cancelled = el('div');
      cancelled.style.padding = '8px';
      cancelled.style.opacity = '0.6';
      cancelled.textContent = 'Plan cancelled.';
      progressBox.appendChild(cancelled);
    });

    // Handle abort
    abortBtn.addEventListener('click', async () => {
      if (!executionId) return;
      abortBtn.disabled = true;
      abortBtn.textContent = 'Aborting...';

      try {
        await kernelRequest('execution/kill', { execution_id: executionId });
        if (pollInterval) {
          clearInterval(pollInterval);
          pollInterval = null;
        }
        abortBtn.style.display = 'none';
        statusLine.innerHTML = '<span style="color: #f59e0b;">⚠ Execution aborted by user</span>';
      } catch (e) {
        abortBtn.textContent = 'Abort';
        abortBtn.disabled = false;
        console.error('Abort error:', e);
        statusLine.innerHTML = `<span style="color: #ef4444;">Failed to abort: ${e instanceof Error ? e.message : String(e)}</span>`;
      }
    });

    controls.appendChild(approveBtn);
    controls.appendChild(rejectBtn);
    controls.appendChild(abortBtn);

    progressBox.appendChild(header);
    progressBox.appendChild(progressBarContainer);
    progressBox.appendChild(stepsList);
    progressBox.appendChild(controls);
    progressBox.appendChild(statusLine);

    container.appendChild(progressBox);
  }

  // Main handler for chat messages - called by the code mode view
  async function handleChatMessage(text: string): Promise<ChatRespondResult> {
    // Check if we're in Code Mode (active act with repo_path AND viewing RIVA)
    // CAIRN view should NOT trigger code mode - it's for conversational chat
    const activeAct = actsCache.find((a) => a.act_id === activeActId);
    const isCodeMode = activeAct && activeAct.repo_path && currentAgent === 'riva';

    // Check if message starts with approval words (yes, y, ok, okay, proceed)
    // Allows additional context like "yes proceed" or "yes, generate answers..."
    const startsWithApproval = text.toLowerCase().match(/^(yes|y|ok|okay|proceed)\b/);
    const startsWithRejection = text.toLowerCase().match(/^(no|n|cancel|abort)\b/);

    // If in Code Mode and user approves (starts with yes/ok/proceed), execute the plan
    if (isCodeMode && startsWithApproval) {
      return handleCodeModeApproval();
    }

    // If in Code Mode and not a rejection, use async planning for new requests
    if (isCodeMode && !startsWithRejection) {
      return handleCodeModePlanning(text, activeActId!);
    }

    try {
      const res = (await kernelRequest('chat/respond', {
        text,
        conversation_id: currentConversationId,
        agent_type: currentAgent,  // Pass current agent for persona selection
      })) as ChatRespondResult;

      // Update conversation ID for context continuity
      currentConversationId = res.conversation_id;

      // Store response data
      messageDataStore.push(res);

      // Code Mode: Handle diff preview if present
      if (res.diff_preview && res.diff_preview.preview) {
        const preview = res.diff_preview.preview;
        const sessionId = res.diff_preview.session_id;
        const onComplete = () => {
          console.log('Diff preview completed');
        };
        // Show the diff overlay
        diffPreviewOverlay.show(preview, sessionId, onComplete);
      }

      // Check if there are pending approvals to display
      if (res.pending_approval_id) {
        // Fetch and display the pending approval
        const approvalsRes = await kernelRequest('approval/pending', {
          conversation_id: currentConversationId
        }) as ApprovalPendingResult;

        // Check if this is a multi-step plan (approvals with plan_id)
        const planApprovals = approvalsRes.approvals.filter(a => a.plan_id);

        // If there's a plan, we note it in the response for the UI to handle
        if (planApprovals.length > 0) {
          const planId = planApprovals[0].plan_id;
          try {
            // Try to get full plan preview
            const planPreview = await kernelRequest('plan/preview', {
              conversation_id: currentConversationId,
              plan_id: planId
            }) as PlanPreviewResult;

            if (planPreview.has_plan && planPreview.steps && planPreview.steps.length > 0) {
              // Add plan info to the response message
              const planSteps = planPreview.steps.map(s => `• ${s.title}`).join('\n');
              res.answer = `${res.answer}\n\n**Plan:**\n${planSteps}\n\nApprove to execute this plan.`;
            }
          } catch {
            // Fallback - add approval notice
            res.answer = `${res.answer}\n\n_Pending approval required. Check The Play overlay for details._`;
          }
        }
      }

      return res;
    } catch (e) {
      return {
        answer: `Error: ${String(e)}`,
        conversation_id: currentConversationId || '',
        message_id: '',
        message_type: 'error',
        tool_calls: [],
        thinking_steps: [],
        pending_approval_id: null,
      };
    }
  }

  // Handler for Code Mode planning with real-time progress
  async function handleCodeModePlanning(text: string, actId: string): Promise<ChatRespondResult> {
    type CodePlanStartResult = { planning_id: string; status: string; prompt: string };
    type CodePlanningState = {
      planning_id: string;
      phase: string;
      phase_name: string;
      phase_description: string;
      phase_index: number;
      activity_log: string[];
      is_complete: boolean;
      success: boolean | null;
      error: string | null;
      elapsed_seconds: number;
      started_at: string;
    };
    type CodePlanResultResponse = {
      success: boolean;
      error?: string;
      response_text?: string;
      plan_id?: string;
      message_id?: string;
    };

    try {
      // Ensure we have a conversation ID
      if (!currentConversationId) {
        currentConversationId = `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      }

      // Start async planning
      const startRes = await kernelRequest('code/plan/start', {
        prompt: text,
        conversation_id: currentConversationId,
        act_id: actId,
      }) as CodePlanStartResult;

      const planningId = startRes.planning_id;
      console.log('[CodeMode] Planning started:', planningId);

      // Poll for progress and update UI
      let lastLogLength = 0;
      let planningComplete = false;
      let pollCount = 0;
      const maxPolls = 300; // 5 minutes max (1s intervals)

      while (!planningComplete && pollCount < maxPolls) {
        await new Promise(resolve => setTimeout(resolve, 1000)); // 1 second interval
        pollCount++;

        try {
          const stateRes = await kernelRequest('code/plan/state', {
            planning_id: planningId,
          }) as CodePlanningState;

          // Log new activity (streaming progress to console for now)
          if (stateRes.activity_log && stateRes.activity_log.length > lastLogLength) {
            const newLogs = stateRes.activity_log.slice(lastLogLength);
            for (const log of newLogs) {
              console.log('[CodeMode]', log);
            }
            lastLogLength = stateRes.activity_log.length;

            // Update Code Mode view with progress
            // Use the backend phase key (e.g., "analyzing_prompt", "generating_criteria")
            // which maps to UI phases via PHASE_KEY_MAP
            codeModeView.updateExecutionState({
              status: stateRes.phase,  // Backend phase key for UI mapping
              phase: stateRes.phase_name,  // Human-readable name
              phase_description: stateRes.phase_description,
              output_lines: stateRes.activity_log,
              elapsed_seconds: stateRes.elapsed_seconds,
              is_complete: false,
              execution_id: planningId,
              prompt: text,
            });
          }

          planningComplete = stateRes.is_complete;

          if (planningComplete) {
            console.log('[CodeMode] Planning complete, success:', stateRes.success);
            if (!stateRes.success) {
              return {
                answer: `**Code Mode Error:** Planning failed.\n\n${stateRes.error || 'Unknown error'}`,
                conversation_id: currentConversationId || '',
                message_id: '',
                message_type: 'error',
                tool_calls: [],
                thinking_steps: [],
                pending_approval_id: null,
              };
            }
          }
        } catch (pollErr) {
          console.error('[CodeMode] Poll error:', pollErr);
          // Continue polling on error
        }
      }

      if (!planningComplete) {
        return {
          answer: '**Code Mode Error:** Planning timed out.',
          conversation_id: currentConversationId || '',
          message_id: '',
          message_type: 'error',
          tool_calls: [],
          thinking_steps: [],
          pending_approval_id: null,
        };
      }

      // Get final result
      const resultRes = await kernelRequest('code/plan/result', {
        planning_id: planningId,
        conversation_id: currentConversationId,
      }) as CodePlanResultResponse;

      if (!resultRes.success) {
        return {
          answer: `**Code Mode Error:** ${resultRes.error || 'Failed to get plan result'}`,
          conversation_id: currentConversationId || '',
          message_id: '',
          message_type: 'error',
          tool_calls: [],
          thinking_steps: [],
          pending_approval_id: null,
        };
      }

      return {
        answer: resultRes.response_text || 'Plan ready.',
        conversation_id: currentConversationId || '',
        message_id: resultRes.message_id || '',
        message_type: 'code_plan_preview',
        tool_calls: [],
        thinking_steps: [],
        pending_approval_id: resultRes.plan_id || null,
      };

    } catch (e) {
      console.error('[CodeMode] Planning error:', e);
      return {
        answer: `**Code Mode Error:** ${String(e)}`,
        conversation_id: currentConversationId || '',
        message_id: '',
        message_type: 'error',
        tool_calls: [],
        thinking_steps: [],
        pending_approval_id: null,
      };
    }
  }

  // Handler for Code Mode approval - starts streaming execution
  async function handleCodeModeApproval(): Promise<ChatRespondResult> {
    type CodeApproveResult = {
      execution_id: string;
      status: string;
      message?: string;
    };
    type CodeExecStateResult = {
      execution_id: string;
      status: string;
      phase: string;
      phase_description: string;
      phase_index: number;
      output_lines: string[];
      is_complete: boolean;
      success: boolean | null;
      error: string | null;
      elapsed_seconds: number;
      steps_completed: number;
      steps_total: number;
      iteration: number;
      max_iterations: number;
    };

    try {
      console.log('[CodeMode] Approving plan and starting execution...');

      // Show immediate feedback
      codeModeView.updateExecutionState({
        status: 'starting',
        phase: 'Approving',
        phase_description: 'Starting execution...',
        phase_index: 0,
        output_lines: ['Approving plan...'],
        elapsed_seconds: 0,
        is_complete: false,
        iteration: 0,
        max_iterations: 10,
        steps_completed: 0,
        steps_total: 0,
      });

      // Call code/plan/approve to start streaming execution
      const approveRes = await kernelRequest('code/plan/approve', {
        conversation_id: currentConversationId || '',
        plan_id: null, // Will use pending plan from DB
      }) as CodeApproveResult;

      if (!approveRes.execution_id) {
        throw new Error('No execution_id returned from approval');
      }

      const executionId = approveRes.execution_id;
      console.log('[CodeMode] Execution started:', executionId);

      // Start polling for execution state
      const pollInterval = 500; // Poll every 500ms for responsiveness
      const maxPolls = 1200; // 10 minutes max (500ms * 1200)
      let pollCount = 0;
      let executionComplete = false;
      let lastOutputLength = 0;

      while (!executionComplete && pollCount < maxPolls) {
        await new Promise(resolve => setTimeout(resolve, pollInterval));
        pollCount++;

        try {
          const stateRes = await kernelRequest('code/exec/state', {
            execution_id: executionId,
          }) as CodeExecStateResult;

          // Log new output lines
          if (stateRes.output_lines && stateRes.output_lines.length > lastOutputLength) {
            const newLines = stateRes.output_lines.slice(lastOutputLength);
            for (const line of newLines) {
              console.log('[CodeMode Exec]', line);
            }
            lastOutputLength = stateRes.output_lines.length;
          }

          // Update Code Mode view with execution state
          codeModeView.updateExecutionState({
            status: stateRes.status,
            phase: stateRes.phase,
            phase_description: stateRes.phase_description,
            phase_index: stateRes.phase_index,
            output_lines: stateRes.output_lines || [],
            elapsed_seconds: stateRes.elapsed_seconds,
            is_complete: stateRes.is_complete,
            iteration: stateRes.iteration,
            max_iterations: stateRes.max_iterations,
            steps_completed: stateRes.steps_completed,
            steps_total: stateRes.steps_total,
          });

          executionComplete = stateRes.is_complete;

          if (executionComplete) {
            const resultMessage = stateRes.success
              ? '**Execution completed successfully!**'
              : `**Execution failed:** ${stateRes.error || 'Unknown error'}`;

            return {
              answer: resultMessage,
              conversation_id: currentConversationId || '',
              message_id: '',
              message_type: stateRes.success ? 'code_execution_complete' : 'error',
              tool_calls: [],
              thinking_steps: [],
              pending_approval_id: null,
            };
          }
        } catch (pollErr) {
          console.error('[CodeMode] Execution poll error:', pollErr);
          // Continue polling on error
        }
      }

      if (!executionComplete) {
        return {
          answer: '**Code Mode Error:** Execution timed out.',
          conversation_id: currentConversationId || '',
          message_id: '',
          message_type: 'error',
          tool_calls: [],
          thinking_steps: [],
          pending_approval_id: null,
        };
      }

      return {
        answer: 'Execution completed.',
        conversation_id: currentConversationId || '',
        message_id: '',
        message_type: 'code_execution_complete',
        tool_calls: [],
        thinking_steps: [],
        pending_approval_id: null,
      };

    } catch (e) {
      console.error('[CodeMode] Approval error:', e);
      const errorMessage = String(e);

      // Update Code Mode UI to show error state
      codeModeView.updateExecutionState({
        status: 'error',
        phase: 'Error',
        phase_description: 'Execution failed',
        phase_index: 0,
        output_lines: ['Approving plan...', `Error: ${errorMessage}`],
        elapsed_seconds: 0,
        is_complete: true,
        success: false,
        error: errorMessage,
        iteration: 0,
        max_iterations: 10,
        steps_completed: 0,
        steps_total: 0,
      });

      return {
        answer: `**Code Mode Error:** ${errorMessage}`,
        conversation_id: currentConversationId || '',
        message_id: '',
        message_type: 'error',
        tool_calls: [],
        thinking_steps: [],
        pending_approval_id: null,
      };
    }
  }

  // Note: The old send button and input listeners are now handled by the Code Mode view

  // Load system status
  async function refreshSystemStatus() {
    try {
      const result = await kernelRequest('tools/call', {
        name: 'linux_system_info',
        arguments: {}
      }) as { result: SystemInfoResult };

      const info = result.result ?? result as unknown as SystemInfoResult;

      const memPercent = info.memory_percent ?? 0;
      const diskPercent = info.disk_percent ?? 0;
      const loadAvg = info.load_avg ?? [0, 0, 0];

      systemStatus.innerHTML = `
        <div style="margin-bottom: 6px"><strong>${info.hostname ?? 'Unknown'}</strong></div>
        <div style="opacity: 0.8; margin-bottom: 4px">${info.distro ?? 'Linux'}</div>
        <div style="margin-bottom: 4px">Kernel: ${info.kernel ?? 'N/A'}</div>
        <div style="margin-bottom: 4px">Uptime: ${info.uptime ?? 'N/A'}</div>
        <div style="margin-bottom: 6px">
          <div style="display: flex; justify-content: space-between;">
            <span>Memory</span>
            <span>${memPercent.toFixed(0)}%</span>
          </div>
          <div style="height: 4px; background: #e5e7eb; border-radius: 2px; overflow: hidden;">
            <div style="height: 100%; width: ${memPercent}%; background: ${memPercent > 80 ? '#ef4444' : memPercent > 60 ? '#f59e0b' : '#22c55e'}"></div>
          </div>
        </div>
        <div style="margin-bottom: 6px">
          <div style="display: flex; justify-content: space-between;">
            <span>Disk (/)</span>
            <span>${diskPercent.toFixed(0)}%</span>
          </div>
          <div style="height: 4px; background: #e5e7eb; border-radius: 2px; overflow: hidden;">
            <div style="height: 100%; width: ${diskPercent}%; background: ${diskPercent > 90 ? '#ef4444' : diskPercent > 75 ? '#f59e0b' : '#22c55e'}"></div>
          </div>
        </div>
        <div style="opacity: 0.8">Load: ${loadAvg[0].toFixed(2)} ${loadAvg[1].toFixed(2)} ${loadAvg[2].toFixed(2)}</div>
      `;
    } catch (e) {
      systemStatus.innerHTML = `<span style="opacity: 0.6">Could not load system info</span>`;
    }
  }

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    const chatInput = codeModeView.getChatInput();

    // Ctrl+K or Cmd+K to focus input
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      chatInput.focus();
      chatInput.select();
    }

    // Ctrl+L to clear chat
    if ((e.ctrlKey || e.metaKey) && e.key === 'l') {
      e.preventDefault();
      codeModeView.clearChat();
      append('reos', 'Chat cleared. How can I help you with your Linux system?');
    }

    // Ctrl+R to refresh system status
    if ((e.ctrlKey || e.metaKey) && e.key === 'r' && !e.shiftKey) {
      e.preventDefault();
      void refreshSystemStatus();
    }

    // Escape to clear input
    if (e.key === 'Escape' && document.activeElement === chatInput) {
      chatInput.value = '';
      chatInput.blur();
    }
  });

  // Initial load
  void (async () => {
    try {
      // Load system status
      await refreshSystemStatus();
      // Refresh every 30 seconds
      setInterval(() => {
        void refreshSystemStatus();
      }, 30000);

      await refreshActs();
      if (activeActId) await refreshScenes(activeActId);

      // Welcome message
      append('reos', 'Welcome to Talking Rock! I\'m your Linux assistant. Ask me anything about your system, or use the quick actions on the left. Keyboard shortcuts: Ctrl+K to focus, Ctrl+L to clear, Ctrl+R to refresh status.');
    } catch (e) {
      showJsonInInspector('Startup error', { error: String(e) });
    }
  })();
}

async function buildMeWindow() {
  const root = document.getElementById('app');
  if (!root) return;
  root.innerHTML = '';

  const wrap = el('div');
  wrap.style.padding = '12px';
  wrap.style.height = '100vh';
  wrap.style.boxSizing = 'border-box';
  wrap.style.overflow = 'auto';

  const title = el('div');
  title.textContent = 'Me (The Play)';
  title.style.fontWeight = '600';
  title.style.marginBottom = '10px';

  const body = el('pre');
  body.style.margin = '0';
  body.style.whiteSpace = 'pre-wrap';

  wrap.appendChild(title);
  wrap.appendChild(body);
  root.appendChild(wrap);

  try {
    const res = (await kernelRequest('play/me/read', {})) as PlayMeReadResult;
    body.textContent = res.markdown ?? '';
  } catch (e) {
    body.textContent = `Error: ${String(e)}`;
  }
}

async function buildDashboardWindow() {
  const root = document.getElementById('app');
  if (!root) return;
  root.innerHTML = '';

  const wrap = el('div');
  wrap.style.cssText = `
    padding: 20px;
    height: 100vh;
    box-sizing: border-box;
    overflow: auto;
    font-family: system-ui, sans-serif;
    background: #1a1a1a;
    color: #e5e7eb;
  `;

  const header = el('div');
  header.style.cssText = `
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
  `;

  const title = el('div');
  title.textContent = '💻 System Dashboard';
  title.style.cssText = 'font-weight: 600; font-size: 20px; color: #fff;';

  const refreshBtn = el('button');
  refreshBtn.textContent = '↻ Refresh';
  refreshBtn.style.cssText = `
    padding: 8px 16px;
    font-size: 12px;
    border: 1px solid rgba(255,255,255,0.2);
    border-radius: 6px;
    background: rgba(255,255,255,0.1);
    color: #e5e7eb;
    cursor: pointer;
    transition: all 0.2s;
  `;
  refreshBtn.addEventListener('mouseenter', () => {
    refreshBtn.style.background = 'rgba(255,255,255,0.2)';
  });
  refreshBtn.addEventListener('mouseleave', () => {
    refreshBtn.style.background = 'rgba(255,255,255,0.1)';
  });

  header.appendChild(title);
  header.appendChild(refreshBtn);

  // System metrics row (CPU, RAM, Disk, GPU)
  const metricsRow = el('div');
  metricsRow.style.cssText = `
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 24px;
  `;

  // Gauge helper with description and detail value
  function createGauge(label: string, icon: string, description: string): {
    container: HTMLElement;
    value: HTMLElement;
    bar: HTMLElement;
    detail: HTMLElement;
    setHidden: (hidden: boolean) => void;
  } {
    const container = el('div');
    container.style.cssText = `
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 12px;
      padding: 16px;
    `;

    const labelRow = el('div');
    labelRow.style.cssText = 'display: flex; align-items: center; gap: 8px; margin-bottom: 4px;';
    labelRow.innerHTML = `<span style="font-size: 18px;">${icon}</span><span style="font-weight: 500; color: rgba(255,255,255,0.8);">${label}</span>`;

    const desc = el('div');
    desc.style.cssText = 'font-size: 11px; color: rgba(255,255,255,0.5); margin-bottom: 10px;';
    desc.textContent = description;

    const value = el('div');
    value.style.cssText = 'font-size: 28px; font-weight: 700; color: #22c55e; margin-bottom: 4px;';
    value.textContent = '--%';

    const detail = el('div');
    detail.style.cssText = 'font-size: 11px; color: rgba(255,255,255,0.6); margin-bottom: 8px;';
    detail.textContent = '';

    const barContainer = el('div');
    barContainer.style.cssText = `
      height: 8px;
      background: rgba(255,255,255,0.1);
      border-radius: 4px;
      overflow: hidden;
    `;

    const bar = el('div');
    bar.style.cssText = `
      height: 100%;
      width: 0%;
      background: #22c55e;
      border-radius: 4px;
      transition: width 0.3s, background 0.3s;
    `;
    barContainer.appendChild(bar);

    container.appendChild(labelRow);
    container.appendChild(desc);
    container.appendChild(value);
    container.appendChild(detail);
    container.appendChild(barContainer);

    return {
      container,
      value,
      bar,
      detail,
      setHidden: (hidden: boolean) => {
        container.style.display = hidden ? 'none' : 'block';
      }
    };
  }

  const cpuGauge = createGauge('CPU', '⚡', 'Processing power usage');
  const ramGauge = createGauge('Memory', '💾', 'RAM consumption');
  const diskGauge = createGauge('Disk', '📁', 'Storage space used');
  const gpuGauge = createGauge('GPU', '🎮', 'Graphics processor load');

  metricsRow.appendChild(cpuGauge.container);
  metricsRow.appendChild(ramGauge.container);
  metricsRow.appendChild(diskGauge.container);
  metricsRow.appendChild(gpuGauge.container);

  // Initially hide GPU gauge until we know if one is available
  gpuGauge.setHidden(true);

  // Grid layout for sections
  const grid = el('div');
  grid.style.cssText = `
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
  `;

  // Section helper
  function createSection(sectionTitle: string, icon: string): { section: HTMLElement; content: HTMLElement } {
    const section = el('div');
    section.style.cssText = `
      background: rgba(255,255,255,0.05);
      border-radius: 12px;
      border: 1px solid rgba(255,255,255,0.1);
      padding: 16px;
      min-height: 200px;
    `;

    const sectionHeader = el('div');
    sectionHeader.style.cssText = `
      font-weight: 600;
      font-size: 14px;
      margin-bottom: 12px;
      color: rgba(255,255,255,0.9);
      display: flex;
      align-items: center;
      gap: 8px;
    `;
    sectionHeader.innerHTML = `<span>${icon}</span>${sectionTitle}`;

    const content = el('div');
    content.style.cssText = 'font-size: 13px;';

    section.appendChild(sectionHeader);
    section.appendChild(content);

    return { section, content };
  }

  // Create sections
  const servicesSection = createSection('Services', '🔧');
  const containersSection = createSection('Containers', '🐳');
  const portsSection = createSection('Listening Ports', '🔌');
  const trafficSection = createSection('Network Traffic', '📡');

  grid.appendChild(servicesSection.section);
  grid.appendChild(containersSection.section);
  grid.appendChild(portsSection.section);
  grid.appendChild(trafficSection.section);

  wrap.appendChild(header);
  wrap.appendChild(metricsRow);
  wrap.appendChild(grid);
  root.appendChild(wrap);

  // Helper to get color based on percentage
  function getGaugeColor(percent: number): string {
    if (percent >= 90) return '#ef4444';
    if (percent >= 70) return '#f59e0b';
    return '#22c55e';
  }

  // Refresh function
  async function refreshDashboard() {
    servicesSection.content.innerHTML = '<span style="opacity: 0.6">Loading...</span>';
    containersSection.content.innerHTML = '<span style="opacity: 0.6">Loading...</span>';
    portsSection.content.innerHTML = '<span style="opacity: 0.6">Loading...</span>';
    trafficSection.content.innerHTML = '<span style="opacity: 0.6">Loading...</span>';

    try {
      const result = await kernelRequest('system/live_state', {}) as SystemLiveStateResult;

      // Update CPU gauge
      const cpuPercent = result.cpu_percent ?? 0;
      const cpuColor = getGaugeColor(cpuPercent);
      cpuGauge.value.textContent = `${Math.round(cpuPercent)}%`;
      cpuGauge.value.style.color = cpuColor;
      cpuGauge.bar.style.width = `${cpuPercent}%`;
      cpuGauge.bar.style.background = cpuColor;
      const cpuModel = result.cpu_model ?? 'Unknown';
      const cpuCores = result.cpu_cores ?? 0;
      cpuGauge.detail.textContent = `${cpuCores} cores • ${cpuModel.substring(0, 30)}${cpuModel.length > 30 ? '...' : ''}`;

      // Update RAM gauge (memory is nested object with percent field)
      const memoryData = result.memory as { percent?: number; used_mb?: number; total_mb?: number } | undefined;
      const ramPercent = memoryData?.percent ?? 0;
      const ramUsedMb = memoryData?.used_mb ?? 0;
      const ramTotalMb = memoryData?.total_mb ?? 0;
      const ramColor = getGaugeColor(ramPercent);
      ramGauge.value.textContent = `${Math.round(ramPercent)}%`;
      ramGauge.value.style.color = ramColor;
      ramGauge.bar.style.width = `${ramPercent}%`;
      ramGauge.bar.style.background = ramColor;
      const ramUsedGb = (ramUsedMb / 1024).toFixed(1);
      const ramTotalGb = (ramTotalMb / 1024).toFixed(1);
      ramGauge.detail.textContent = `${ramUsedGb} GB / ${ramTotalGb} GB used`;

      // Update Disk gauge (disks is array, use first/root disk)
      const disksData = result.disks as Array<{ percent?: number; used_gb?: number; total_gb?: number; mount?: string }> | undefined;
      const firstDisk = disksData && disksData.length > 0 ? disksData[0] : null;
      const diskPercent = firstDisk?.percent ?? 0;
      const diskUsedGb = firstDisk?.used_gb ?? 0;
      const diskTotalGb = firstDisk?.total_gb ?? 0;
      const diskColor = getGaugeColor(diskPercent);
      diskGauge.value.textContent = `${Math.round(diskPercent)}%`;
      diskGauge.value.style.color = diskColor;
      diskGauge.bar.style.width = `${diskPercent}%`;
      diskGauge.bar.style.background = diskColor;
      diskGauge.detail.textContent = `${diskUsedGb.toFixed(0)} GB / ${diskTotalGb.toFixed(0)} GB used`;

      // Update GPU gauge if available
      const gpuData = result.gpu as { name?: string; percent?: number; memory_used_mb?: number; memory_total_mb?: number } | null;
      if (gpuData) {
        gpuGauge.setHidden(false);
        // Update grid to show 4 columns
        metricsRow.style.gridTemplateColumns = 'repeat(4, 1fr)';
        const gpuPercent = gpuData.percent ?? 0;
        const gpuColor = getGaugeColor(gpuPercent);
        gpuGauge.value.textContent = `${Math.round(gpuPercent)}%`;
        gpuGauge.value.style.color = gpuColor;
        gpuGauge.bar.style.width = `${gpuPercent}%`;
        gpuGauge.bar.style.background = gpuColor;
        const gpuMemUsedGb = ((gpuData.memory_used_mb ?? 0) / 1024).toFixed(1);
        const gpuMemTotalGb = ((gpuData.memory_total_mb ?? 0) / 1024).toFixed(1);
        const gpuName = gpuData.name ?? 'Unknown';
        gpuGauge.detail.textContent = `${gpuMemUsedGb}/${gpuMemTotalGb} GB • ${gpuName.substring(0, 20)}`;
      } else {
        gpuGauge.setHidden(true);
        // Use 3 columns when no GPU
        metricsRow.style.gridTemplateColumns = 'repeat(3, 1fr)';
      }

      // Render services
      const services = result.services ?? [];
      if (services.length === 0) {
        servicesSection.content.innerHTML = '<span style="opacity: 0.5; color: rgba(255,255,255,0.6);">No services found</span>';
      } else {
        servicesSection.content.innerHTML = '';
        for (const svc of services) {
          const row = el('div');
          row.style.cssText = `
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
          `;

          const dot = el('span');
          dot.textContent = '●';
          dot.style.cssText = `
            font-size: 10px;
            color: ${svc.status === 'failed' ? '#ef4444' : svc.active ? '#22c55e' : '#6b7280'};
          `;

          const name = el('span');
          name.textContent = svc.name;
          name.style.cssText = 'flex: 1; color: rgba(255,255,255,0.9);';

          const status = el('span');
          status.textContent = svc.status;
          status.style.cssText = `
            font-size: 10px;
            padding: 2px 8px;
            border-radius: 4px;
            background: ${svc.status === 'failed' ? 'rgba(239,68,68,0.2)' : svc.active ? 'rgba(34,197,94,0.2)' : 'rgba(107,114,128,0.2)'};
            color: ${svc.status === 'failed' ? '#ef4444' : svc.active ? '#22c55e' : '#9ca3af'};
          `;

          row.appendChild(dot);
          row.appendChild(name);
          row.appendChild(status);
          servicesSection.content.appendChild(row);
        }
      }

      // Render containers
      const containers = result.containers ?? [];
      if (containers.length === 0) {
        containersSection.content.innerHTML = '<span style="opacity: 0.5; color: rgba(255,255,255,0.6);">No containers found</span>';
      } else {
        containersSection.content.innerHTML = '';
        for (const ctr of containers) {
          const row = el('div');
          row.style.cssText = `
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
          `;

          const isRunning = ctr.status.toLowerCase().includes('up');
          const dot = el('span');
          dot.textContent = '●';
          dot.style.cssText = `font-size: 10px; color: ${isRunning ? '#22c55e' : '#6b7280'};`;

          const name = el('span');
          name.textContent = ctr.name;
          name.style.cssText = 'flex: 1; color: rgba(255,255,255,0.9);';

          const image = el('span');
          image.textContent = ctr.image.split(':')[0].split('/').pop() ?? ctr.image;
          image.style.cssText = `
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 4px;
            background: rgba(255,255,255,0.1);
            color: rgba(255,255,255,0.6);
          `;

          row.appendChild(dot);
          row.appendChild(name);
          row.appendChild(image);
          containersSection.content.appendChild(row);
        }
      }

      // Render ports
      const ports = result.ports ?? [];
      if (ports.length === 0) {
        portsSection.content.innerHTML = '<span style="opacity: 0.5; color: rgba(255,255,255,0.6);">No listening ports</span>';
      } else {
        portsSection.content.innerHTML = '';
        for (const port of ports) {
          const row = el('div');
          row.style.cssText = `
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
          `;

          const portNum = el('span');
          portNum.textContent = `:${port.port}`;
          portNum.style.cssText = `
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
            min-width: 60px;
            color: #60a5fa;
          `;

          const addr = el('span');
          addr.textContent = port.address === '0.0.0.0' || port.address === '*' ? 'all interfaces' : port.address;
          addr.style.cssText = 'flex: 1; color: rgba(255,255,255,0.6);';

          const process = el('span');
          process.textContent = port.process || `PID ${port.pid ?? '?'}`;
          process.style.cssText = `
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 4px;
            background: rgba(59,130,246,0.2);
            color: #93c5fd;
          `;

          row.appendChild(portNum);
          row.appendChild(addr);
          row.appendChild(process);
          portsSection.content.appendChild(row);
        }
      }

      // Render traffic
      const traffic = result.traffic ?? [];
      if (traffic.length === 0) {
        trafficSection.content.innerHTML = '<span style="opacity: 0.5; color: rgba(255,255,255,0.6);">No network interfaces</span>';
      } else {
        trafficSection.content.innerHTML = '';
        for (const iface of traffic) {
          const row = el('div');
          row.style.cssText = `
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
          `;

          const name = el('span');
          name.textContent = iface.interface;
          name.style.cssText = 'font-weight: 500; min-width: 80px; color: rgba(255,255,255,0.9);';

          const rx = el('span');
          rx.innerHTML = `<span style="color: #22c55e;">↓</span> ${iface.rx_formatted}`;
          rx.style.cssText = 'flex: 1; font-family: monospace; font-size: 12px;';

          const tx = el('span');
          tx.innerHTML = `<span style="color: #3b82f6;">↑</span> ${iface.tx_formatted}`;
          tx.style.cssText = 'flex: 1; font-family: monospace; font-size: 12px;';

          row.appendChild(name);
          row.appendChild(rx);
          row.appendChild(tx);
          trafficSection.content.appendChild(row);
        }
      }
    } catch (e) {
      const errorMsg = `<span style="color: #ef4444;">Error: ${String(e)}</span>`;
      servicesSection.content.innerHTML = errorMsg;
      containersSection.content.innerHTML = '';
      portsSection.content.innerHTML = '';
      trafficSection.content.innerHTML = '';

      // Reset gauges on error
      cpuGauge.value.textContent = '--%';
      ramGauge.value.textContent = '--%';
      diskGauge.value.textContent = '--%';
    }
  }

  // Initial load and refresh button
  refreshBtn.addEventListener('click', () => void refreshDashboard());
  await refreshDashboard();

  // Auto-refresh every 10 seconds
  setInterval(() => void refreshDashboard(), 10000);
}

/**
 * Initialize the application with authentication.
 *
 * Security:
 * - Checks for existing session on startup
 * - Shows login screen if not authenticated
 * - Sets up session monitoring for auto-lock
 */
async function initializeApp(): Promise<void> {
  const root = document.getElementById('app');
  if (!root) return;

  // Skip authentication in development mode for faster iteration
  // @ts-ignore - Vite provides import.meta.env
  const skipAuth = import.meta.env.DEV;

  if (skipAuth) {
    console.log('[DEV] Creating dev session...');
    try {
      // Create a dev session on the Rust side
      const { invoke } = await import('@tauri-apps/api/core');
      const result = await invoke('dev_create_session') as { success: boolean; session_token?: string; username?: string; error?: string };

      if (result.success && result.session_token && result.username) {
        // Store the session in localStorage so kernelRequest can use it
        const { setSession } = await import('./kernel');
        setSession(result.session_token, result.username);
        console.log(`[DEV] Session created for user: ${result.username}`);
        buildUi();
        return;
      } else {
        console.error('[DEV] Failed to create dev session:', result.error);
      }
    } catch (e) {
      console.error('[DEV] Failed to create dev session:', e);
    }
    // Fall through to normal auth if dev session fails
  }

  // Check authentication and show login if needed
  const isValid = await checkSessionOrLogin(root, (_username) => {
    // On successful login, build the authenticated UI
    buildUi();
    setupSessionMonitoring();
  });

  if (isValid) {
    // Session is valid, build UI immediately
    buildUi();
    setupSessionMonitoring();
  }
}

/**
 * Set up session monitoring for auto-lock.
 * Monitors for:
 * - Session expiry (periodic validation)
 * - Window visibility changes (potential system lock)
 */
function setupSessionMonitoring(): void {
  // Check session validity every 5 minutes
  setInterval(async () => {
    if (!isAuthenticated()) return;

    const isValid = await validateSession();
    if (!isValid) {
      // Session expired, show lock overlay
      showLockOverlay(() => {
        // Session restored, continue normally
      });
    }
  }, 5 * 60 * 1000);

  // Monitor visibility changes (user might have locked screen)
  document.addEventListener('visibilitychange', async () => {
    if (document.visibilityState === 'visible' && isAuthenticated()) {
      // Coming back from hidden, validate session
      const isValid = await validateSession();
      if (!isValid) {
        showLockOverlay(() => {
          // Session restored
        });
      }
    }
  });
}

// Initialize app on load
initializeApp().catch((err) => {
  console.error('Failed to initialize app:', err);
  // Show error prominently in the UI
  const errorDiv = document.createElement('div');
  errorDiv.style.cssText = `
    position: fixed; top: 0; left: 0; right: 0;
    background: #ef4444; color: white; padding: 12px;
    text-align: center; font-size: 14px; z-index: 9999;
  `;
  errorDiv.textContent = `Failed to initialize Talking Rock: ${err instanceof Error ? err.message : String(err)}`;
  document.body.appendChild(errorDiv);
});
