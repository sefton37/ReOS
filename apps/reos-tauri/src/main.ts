/**
 * ReOS Desktop Application - Natural Language Linux
 *
 * Main entry point for the Tauri-based desktop UI.
 * Communicates with the Python kernel via JSON-RPC over stdio.
 */
import { WebviewWindow } from '@tauri-apps/api/webviewWindow';

import './style.css';

// Modular imports
import { kernelRequest, KernelError } from './kernel';
import { el, rowHeader, label, textInput, textArea, smallButton } from './dom';
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
  ApprovalExplainResult
} from './types';

function buildUi() {
  const query = new URLSearchParams(window.location.search);
  if (query.get('view') === 'me') {
    void buildMeWindow();
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
  navTitle.textContent = 'ReOS for Linux';
  navTitle.style.fontWeight = '600';
  navTitle.style.fontSize = '16px';
  navTitle.style.marginBottom = '12px';

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

  // Services Section
  const servicesSection = el('div');
  servicesSection.className = 'services-section';
  servicesSection.style.marginTop = '12px';

  const servicesHeader = el('div');
  servicesHeader.style.display = 'flex';
  servicesHeader.style.justifyContent = 'space-between';
  servicesHeader.style.alignItems = 'center';
  servicesHeader.style.marginBottom = '8px';

  const servicesTitle = el('div');
  servicesTitle.textContent = 'Services';
  servicesTitle.style.fontWeight = '600';
  servicesTitle.style.fontSize = '13px';
  servicesTitle.style.color = '#666';

  const servicesRefresh = el('button');
  servicesRefresh.textContent = '↻';
  servicesRefresh.style.background = 'transparent';
  servicesRefresh.style.border = 'none';
  servicesRefresh.style.cursor = 'pointer';
  servicesRefresh.style.opacity = '0.6';
  servicesRefresh.style.fontSize = '14px';
  servicesRefresh.title = 'Refresh';

  servicesHeader.appendChild(servicesTitle);
  servicesHeader.appendChild(servicesRefresh);

  const servicesList = el('div');
  servicesList.className = 'services-list';
  servicesList.style.fontSize = '12px';
  servicesList.innerHTML = '<span style="opacity: 0.6">Loading...</span>';

  servicesSection.appendChild(servicesHeader);
  servicesSection.appendChild(servicesList);

  // Containers Section
  const containersSection = el('div');
  containersSection.className = 'containers-section';
  containersSection.style.marginTop = '12px';

  const containersHeader = el('div');
  containersHeader.style.display = 'flex';
  containersHeader.style.justifyContent = 'space-between';
  containersHeader.style.alignItems = 'center';
  containersHeader.style.marginBottom = '8px';

  const containersTitle = el('div');
  containersTitle.textContent = 'Containers';
  containersTitle.style.fontWeight = '600';
  containersTitle.style.fontSize = '13px';
  containersTitle.style.color = '#666';

  const containersRefresh = el('button');
  containersRefresh.textContent = '↻';
  containersRefresh.style.background = 'transparent';
  containersRefresh.style.border = 'none';
  containersRefresh.style.cursor = 'pointer';
  containersRefresh.style.opacity = '0.6';
  containersRefresh.style.fontSize = '14px';
  containersRefresh.title = 'Refresh';

  containersHeader.appendChild(containersTitle);
  containersHeader.appendChild(containersRefresh);

  const containersList = el('div');
  containersList.className = 'containers-list';
  containersList.style.fontSize = '12px';
  containersList.innerHTML = '<span style="opacity: 0.6">Loading...</span>';

  containersSection.appendChild(containersHeader);
  containersSection.appendChild(containersList);

  // Quick Actions Section
  const actionsHeader = el('div');
  actionsHeader.textContent = 'Quick Actions';
  actionsHeader.style.fontWeight = '600';
  actionsHeader.style.marginTop = '12px';
  actionsHeader.style.marginBottom = '8px';
  actionsHeader.style.fontSize = '13px';
  actionsHeader.style.color = '#666';

  const quickActions = el('div');
  quickActions.className = 'quick-actions';
  quickActions.style.display = 'flex';
  quickActions.style.flexDirection = 'column';
  quickActions.style.gap = '4px';
  quickActions.style.marginBottom = '16px';

  const quickActionItems = [
    { label: 'System Info', prompt: 'Show me my system information' },
    { label: 'Disk Usage', prompt: 'How much disk space do I have?' },
    { label: 'Top Processes', prompt: 'What processes are using the most CPU?' },
    { label: 'Running Services', prompt: 'Show me the active services' },
    { label: 'Network Info', prompt: 'Show me my network interfaces and IP addresses' },
    { label: 'Update System', prompt: 'How do I update my system packages?' },
  ];

  for (const action of quickActionItems) {
    const btn = el('button');
    btn.className = 'quick-action-btn';
    btn.textContent = action.label;
    btn.style.textAlign = 'left';
    btn.style.padding = '8px 10px';
    btn.style.fontSize = '12px';
    btn.style.border = '1px solid rgba(209, 213, 219, 0.5)';
    btn.style.borderRadius = '8px';
    btn.style.background = 'rgba(255, 255, 255, 0.3)';
    btn.style.cursor = 'pointer';
    btn.addEventListener('click', () => {
      input.value = action.prompt;
      void onSend();
    });
    quickActions.appendChild(btn);
  }

  // The Play Section
  const meHeader = el('div');
  meHeader.textContent = 'The Play';
  meHeader.style.marginTop = '16px';
  meHeader.style.fontWeight = '600';
  meHeader.style.marginBottom = '8px';
  meHeader.style.fontSize = '13px';
  meHeader.style.color = '#666';

  const meBtn = el('button');
  meBtn.textContent = 'Open Me File';
  meBtn.style.padding = '8px 10px';
  meBtn.style.fontSize = '12px';
  meBtn.style.border = '1px solid rgba(209, 213, 219, 0.5)';
  meBtn.style.borderRadius = '8px';
  meBtn.style.background = 'rgba(255, 255, 255, 0.3)';

  const actsHeader = el('div');
  actsHeader.textContent = 'Acts';
  actsHeader.style.marginTop = '12px';
  actsHeader.style.fontWeight = '600';
  actsHeader.style.fontSize = '12px';

  const actsList = el('div');
  actsList.style.display = 'flex';
  actsList.style.flexDirection = 'column';
  actsList.style.gap = '4px';
  actsList.style.marginTop = '6px';

  nav.appendChild(navTitle);
  nav.appendChild(systemSection);
  nav.appendChild(servicesSection);
  nav.appendChild(containersSection);
  nav.appendChild(actionsHeader);
  nav.appendChild(quickActions);
  nav.appendChild(meHeader);
  nav.appendChild(meBtn);
  nav.appendChild(actsHeader);
  nav.appendChild(actsList);

  const center = el('div');
  center.className = 'center';
  center.style.flex = '1';
  center.style.display = 'flex';
  center.style.flexDirection = 'column';

  const chatLog = el('div');
  chatLog.className = 'chat-log';
  chatLog.style.flex = '1';
  chatLog.style.padding = '12px';
  chatLog.style.overflow = 'auto';

  const inputRow = el('div');
  inputRow.className = 'input-row';
  inputRow.style.display = 'flex';
  inputRow.style.gap = '8px';
  inputRow.style.padding = '12px';
  inputRow.style.borderTop = '1px solid #ddd';

  const input = el('input');
  input.className = 'chat-input';
  input.type = 'text';
  input.placeholder = 'Ask me anything about your Linux system…';
  input.style.flex = '1';

  const send = el('button');
  send.className = 'send-btn';
  send.textContent = 'Send';

  inputRow.appendChild(input);
  inputRow.appendChild(send);

  const inspection = el('div');
  inspection.className = 'inspection';
  inspection.style.width = '420px';
  inspection.style.borderLeft = '1px solid #ddd';
  inspection.style.margin = '0';
  inspection.style.padding = '12px';
  inspection.style.overflow = 'auto';

  const inspectionTitle = el('div');
  inspectionTitle.style.fontWeight = '600';
  inspectionTitle.style.marginBottom = '8px';
  inspectionTitle.textContent = 'Inspection';

  const inspectionBody = el('div');

  inspection.appendChild(inspectionTitle);
  inspection.appendChild(inspectionBody);

  center.appendChild(chatLog);
  center.appendChild(inputRow);

  shell.appendChild(nav);
  shell.appendChild(center);
  shell.appendChild(inspection);

  root.appendChild(shell);

  function append(role: 'user' | 'reos', text: string) {
    const row = el('div');
    row.className = `chat-row ${role}`;

    const bubble = el('div');
    bubble.className = `chat-bubble ${role}`;
    bubble.textContent = text;

    row.appendChild(bubble);
    chatLog.appendChild(row);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function appendThinking(): { row: HTMLDivElement; bubble: HTMLDivElement } {
    const row = el('div') as HTMLDivElement;
    row.className = 'chat-row reos';

    const bubble = el('div') as HTMLDivElement;
    bubble.className = 'chat-bubble reos thinking';

    const dots = el('span') as HTMLSpanElement;
    dots.className = 'typing-dots';
    dots.innerHTML = '<span></span><span></span><span></span>';
    bubble.appendChild(dots);

    row.appendChild(bubble);
    chatLog.appendChild(row);
    chatLog.scrollTop = chatLog.scrollHeight;
    return { row, bubble };
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

  function showJsonInInspector(title: string, obj: unknown) {
    inspectionTitle.textContent = title;
    inspectionBody.innerHTML = '';
    const pre = el('pre');
    pre.style.margin = '0';
    pre.textContent = JSON.stringify(obj ?? null, null, 2);
    inspectionBody.appendChild(pre);
  }

  async function openMeWindow() {
    try {
      const existing = await WebviewWindow.getByLabel('me');
      if (existing) {
        await existing.setFocus();
        return;
      }
    } catch {
      // Best effort: if getByLabel fails, fall through and create a new window.
    }

    const w = new WebviewWindow('me', {
      title: 'Me — ReOS',
      url: '/?view=me',
      width: 900,
      height: 700
    });
    void w;
  }

  meBtn.addEventListener('click', () => void openMeWindow());

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
    inspectionBody.appendChild(actSave);
    inspectionBody.appendChild(label('Create new act'));
    inspectionBody.appendChild(actCreateRow);

    void (async () => {
      if (!activeAct) return;
      actTitle.value = activeAct.title ?? '';
      actNotes.value = activeAct.notes ?? '';
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
        const tStatus = textInput(b.status ?? '');
        const tLink = textInput(b.link ?? '');
        const tNotes = textArea(b.notes ?? '', 80);
        const save = smallButton('Save Beat');

        detail.appendChild(label('Title'));
        detail.appendChild(tTitle);
        detail.appendChild(label('Status'));
        detail.appendChild(tStatus);
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
              status: tStatus.value,
              link: tLink.value || null,
              notes: tNotes.value
            });
            await refreshBeats(activeActId, selectedSceneId);
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

    actsList.innerHTML = '';
    for (const a of actsCache) {
      const btn = el('button');
      btn.textContent = a.act_id === activeActId ? `• ${a.title}` : a.title;
      btn.addEventListener('click', async () => {
        const setRes = (await kernelRequest('play/acts/set_active', { act_id: a.act_id })) as PlayActsListResult;
        activeActId = setRes.active_act_id ?? null;
        selectedSceneId = null;
        selectedBeatId = null;
        await refreshActs();
        if (activeActId) await refreshScenes(activeActId);
      });
      actsList.appendChild(btn);
    }

    if (actsCache.length === 0) {
      const empty = el('div');
      empty.textContent = '(no acts yet)';
      empty.style.opacity = '0.7';
      actsList.appendChild(empty);
    }

    renderPlayInspector();
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
    renderPlayInspector();
  }


  // Track current conversation for context continuity
  let currentConversationId: string | null = null;

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

  async function onSend() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    append('user', text);

    // Immediately show an empty ReOS bubble with a thinking animation.
    const pending = appendThinking();

    // Ensure the browser paints the new bubbles before we start the kernel RPC.
    // Note: `requestAnimationFrame` alone can resume into a microtask that still
    // runs before paint, so we also yield a macrotask.
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    await new Promise<void>((resolve) => setTimeout(resolve, 0));

    try {
      const res = (await kernelRequest('chat/respond', {
        text,
        conversation_id: currentConversationId
      })) as ChatRespondResult;

      // Update conversation ID for context continuity
      currentConversationId = res.conversation_id;

      pending.bubble.classList.remove('thinking');
      pending.bubble.textContent = res.answer ?? '(no answer)';

      // Check if there are pending approvals to display
      if (res.pending_approval_id) {
        // Fetch and display the pending approval
        const approvalsRes = await kernelRequest('approval/pending', {
          conversation_id: currentConversationId
        }) as ApprovalPendingResult;

        // Check if this is a multi-step plan (approvals with plan_id)
        const planApprovals = approvalsRes.approvals.filter(a => a.plan_id);
        const singleApprovals = approvalsRes.approvals.filter(a => !a.plan_id);

        // If there's a plan, try to fetch plan details and show progress UI
        if (planApprovals.length > 0) {
          const planId = planApprovals[0].plan_id;
          try {
            // Try to get full plan preview
            const planPreview = await kernelRequest('plan/preview', {
              conversation_id: currentConversationId,
              plan_id: planId
            }) as PlanPreviewResult;

            if (planPreview.has_plan && planPreview.steps && planPreview.steps.length > 1) {
              // Multi-step plan - use progress visualization
              appendPlanProgress(planPreview, pending.row, async () => {
                // Approve the plan and start execution
                const approveResult = await kernelRequest('plan/approve', {
                  conversation_id: currentConversationId,
                  plan_id: planId
                }) as PlanApproveResult;
                return approveResult.execution_id ? { execution_id: approveResult.execution_id } : null;
              });
            } else {
              // Single step plan - use regular command preview
              for (const approval of planApprovals) {
                appendCommandPreview(approval, pending.row);
              }
            }
          } catch {
            // Fallback to command preview if plan/preview fails
            for (const approval of planApprovals) {
              appendCommandPreview(approval, pending.row);
            }
          }
        }

        // Show single command approvals
        for (const approval of singleApprovals) {
          appendCommandPreview(approval, pending.row);
        }
      }
    } catch (e) {
      pending.bubble.classList.remove('thinking');
      pending.bubble.textContent = `Error: ${String(e)}`;
    }
  }

  send.addEventListener('click', () => void onSend());
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') void onSend();
  });

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

  // Load live state (services, containers)
  async function refreshLiveState() {
    try {
      const result = await kernelRequest('system/live_state', {}) as SystemLiveStateResult;

      // Render services list
      const services = result.services ?? [];
      if (services.length === 0) {
        servicesList.innerHTML = '<span style="opacity: 0.6">No services found</span>';
      } else {
        servicesList.innerHTML = '';
        // Show top 8 services, prioritizing active/failed
        const sortedServices = [...services].sort((a, b) => {
          if (a.status === 'failed' && b.status !== 'failed') return -1;
          if (b.status === 'failed' && a.status !== 'failed') return 1;
          if (a.active && !b.active) return -1;
          if (b.active && !a.active) return 1;
          return a.name.localeCompare(b.name);
        }).slice(0, 8);

        for (const svc of sortedServices) {
          const row = el('div');
          row.style.display = 'flex';
          row.style.alignItems = 'center';
          row.style.justifyContent = 'space-between';
          row.style.padding = '4px 0';
          row.style.borderBottom = '1px solid rgba(0,0,0,0.05)';

          const nameCol = el('div');
          nameCol.style.display = 'flex';
          nameCol.style.alignItems = 'center';
          nameCol.style.gap = '6px';
          nameCol.style.flex = '1';
          nameCol.style.overflow = 'hidden';

          const dot = el('span');
          dot.textContent = '●';
          dot.style.fontSize = '8px';
          if (svc.status === 'failed') {
            dot.style.color = '#ef4444';
          } else if (svc.active) {
            dot.style.color = '#22c55e';
          } else {
            dot.style.color = '#9ca3af';
          }

          const name = el('span');
          name.textContent = svc.name.replace('.service', '');
          name.style.overflow = 'hidden';
          name.style.textOverflow = 'ellipsis';
          name.style.whiteSpace = 'nowrap';

          nameCol.appendChild(dot);
          nameCol.appendChild(name);

          const actions = el('div');
          actions.style.display = 'flex';
          actions.style.gap = '4px';

          const logsBtn = el('button');
          logsBtn.textContent = '📋';
          logsBtn.title = 'View logs';
          logsBtn.style.background = 'transparent';
          logsBtn.style.border = 'none';
          logsBtn.style.cursor = 'pointer';
          logsBtn.style.fontSize = '10px';
          logsBtn.style.padding = '2px';
          logsBtn.addEventListener('click', async () => {
            input.value = `Show me the logs for ${svc.name}`;
            void onSend();
          });

          const toggleBtn = el('button');
          toggleBtn.textContent = svc.active ? '⏹' : '▶';
          toggleBtn.title = svc.active ? 'Stop service' : 'Start service';
          toggleBtn.style.background = 'transparent';
          toggleBtn.style.border = 'none';
          toggleBtn.style.cursor = 'pointer';
          toggleBtn.style.fontSize = '10px';
          toggleBtn.style.padding = '2px';
          toggleBtn.addEventListener('click', async () => {
            const action = svc.active ? 'stop' : 'start';
            input.value = `${action} the ${svc.name} service`;
            void onSend();
          });

          actions.appendChild(logsBtn);
          actions.appendChild(toggleBtn);

          row.appendChild(nameCol);
          row.appendChild(actions);
          servicesList.appendChild(row);
        }
      }

      // Render containers list
      const containers = result.containers ?? [];
      if (containers.length === 0) {
        containersList.innerHTML = '<span style="opacity: 0.6">No containers running</span>';
      } else {
        containersList.innerHTML = '';
        // Show up to 8 containers
        const displayContainers = containers.slice(0, 8);

        for (const ctr of displayContainers) {
          const row = el('div');
          row.style.display = 'flex';
          row.style.alignItems = 'center';
          row.style.justifyContent = 'space-between';
          row.style.padding = '4px 0';
          row.style.borderBottom = '1px solid rgba(0,0,0,0.05)';

          const nameCol = el('div');
          nameCol.style.display = 'flex';
          nameCol.style.alignItems = 'center';
          nameCol.style.gap = '6px';
          nameCol.style.flex = '1';
          nameCol.style.overflow = 'hidden';

          const dot = el('span');
          dot.textContent = '●';
          dot.style.fontSize = '8px';
          const isRunning = ctr.status.toLowerCase().includes('up');
          dot.style.color = isRunning ? '#22c55e' : '#9ca3af';

          const name = el('span');
          name.textContent = ctr.name;
          name.style.overflow = 'hidden';
          name.style.textOverflow = 'ellipsis';
          name.style.whiteSpace = 'nowrap';
          name.title = `${ctr.image}\n${ctr.status}`;

          nameCol.appendChild(dot);
          nameCol.appendChild(name);

          const actions = el('div');
          actions.style.display = 'flex';
          actions.style.gap = '4px';

          const logsBtn = el('button');
          logsBtn.textContent = '📋';
          logsBtn.title = 'View logs';
          logsBtn.style.background = 'transparent';
          logsBtn.style.border = 'none';
          logsBtn.style.cursor = 'pointer';
          logsBtn.style.fontSize = '10px';
          logsBtn.style.padding = '2px';
          logsBtn.addEventListener('click', async () => {
            input.value = `Show me the logs for the ${ctr.name} container`;
            void onSend();
          });

          const stopBtn = el('button');
          stopBtn.textContent = isRunning ? '⏹' : '▶';
          stopBtn.title = isRunning ? 'Stop container' : 'Start container';
          stopBtn.style.background = 'transparent';
          stopBtn.style.border = 'none';
          stopBtn.style.cursor = 'pointer';
          stopBtn.style.fontSize = '10px';
          stopBtn.style.padding = '2px';
          stopBtn.addEventListener('click', async () => {
            const action = isRunning ? 'stop' : 'start';
            input.value = `${action} the ${ctr.name} container`;
            void onSend();
          });

          actions.appendChild(logsBtn);
          actions.appendChild(stopBtn);

          row.appendChild(nameCol);
          row.appendChild(actions);
          containersList.appendChild(row);
        }
      }
    } catch (e) {
      servicesList.innerHTML = '<span style="opacity: 0.6">Could not load services</span>';
      containersList.innerHTML = '<span style="opacity: 0.6">Could not load containers</span>';
    }
  }

  // Wire up refresh buttons
  servicesRefresh.addEventListener('click', () => void refreshLiveState());
  containersRefresh.addEventListener('click', () => void refreshLiveState());

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    // Ctrl+K or Cmd+K to focus input
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      input.focus();
      input.select();
    }

    // Ctrl+L to clear chat
    if ((e.ctrlKey || e.metaKey) && e.key === 'l') {
      e.preventDefault();
      chatLog.innerHTML = '';
      append('reos', 'Chat cleared. How can I help you with your Linux system?');
    }

    // Ctrl+R to refresh system status and live state
    if ((e.ctrlKey || e.metaKey) && e.key === 'r' && !e.shiftKey) {
      e.preventDefault();
      void refreshSystemStatus();
      void refreshLiveState();
    }

    // Escape to clear input
    if (e.key === 'Escape' && document.activeElement === input) {
      input.value = '';
      input.blur();
    }
  });

  // Initial load
  void (async () => {
    try {
      // Load system status and live state
      await refreshSystemStatus();
      await refreshLiveState();
      // Refresh every 10 seconds for live feel
      setInterval(() => {
        void refreshSystemStatus();
        void refreshLiveState();
      }, 10000);

      await refreshActs();
      if (activeActId) await refreshScenes(activeActId);

      // Welcome message
      append('reos', 'Welcome to ReOS! I\'m your Linux assistant. Ask me anything about your system, or use the quick actions on the left. Keyboard shortcuts: Ctrl+K to focus, Ctrl+L to clear, Ctrl+R to refresh status.');
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

buildUi();
