/**
 * Play Overlay Component
 *
 * Full-screen modal for managing The Play hierarchy:
 * Play → Acts → Scenes → Beats
 *
 * Features:
 * - Left sidebar with tree navigation
 * - Markdown editor with contextual placeholder text
 * - File attachments (stored as path references)
 */

import { open } from '@tauri-apps/plugin-dialog';
import { el } from './dom';
import { kernelRequest } from './kernel';
import type {
  PlayActsListResult,
  PlayScenesListResult,
  PlayBeatsListResult,
  PlayKbReadResult,
  PlayKbWritePreviewResult,
  PlayAttachmentsListResult,
  PlayAttachment,
  PlayLevel,
} from './types';

// Color palette for Acts (matches Python ACT_COLOR_PALETTE)
const ACT_COLOR_PALETTE = [
  '#8b5cf6',  // Purple (violet-500)
  '#3b82f6',  // Blue (blue-500)
  '#10b981',  // Green (emerald-500)
  '#f59e0b',  // Amber (amber-500)
  '#ef4444',  // Red (red-500)
  '#ec4899',  // Pink (pink-500)
  '#06b6d4',  // Cyan (cyan-500)
  '#84cc16',  // Lime (lime-500)
  '#f97316',  // Orange (orange-500)
  '#6366f1',  // Indigo (indigo-500)
  '#14b8a6',  // Teal (teal-500)
  '#a855f7',  // Fuchsia (purple-500)
];

// Placeholder text per level
const PLACEHOLDER_TEXT: Record<PlayLevel, string> = {
  play: `This is The Play - your high-level narrative and vision.

Write your overarching story, goals, and long-term vision here.
Attach strategic documents, vision statements, or reference materials.

This is the root of your journey - everything flows from here.`,

  act: `This is the Act's script - a major chapter in your journey.

Write your story, notes, brainstorm, and narrative of this Act.
Select documents from your hard drive to bring into context.

Acts represent significant phases or themes in your work.`,

  scene: `This is the Scene's script - a specific focus area or project.

Define the intent, timeline, and key details of this Scene.
Attach relevant project documents, specs, or reference files.

Scenes are the concrete initiatives within an Act.`,

  beat: `This is the Beat's script - an individual task or action.

Capture notes, context, and details for this specific Beat.
Link to supporting documents or outputs.

Beats are the atomic units of progress.`,
};

interface PlayOverlayState {
  isOpen: boolean;
  selectedLevel: PlayLevel;
  activeActId: string | null;
  selectedSceneId: string | null;
  selectedBeatId: string | null;
  actsCache: PlayActsListResult['acts'];
  scenesCache: PlayScenesListResult['scenes'];
  beatsCache: PlayBeatsListResult['beats'];
  kbText: string;
  kbPath: string;
  attachments: PlayAttachment[];
  expandedActs: Set<string>;
  expandedScenes: Set<string>;
}

export function createPlayOverlay(onClose: () => void): {
  element: HTMLElement;
  open: (actId?: string, sceneId?: string, beatId?: string) => void;
  close: () => void;
} {
  // State
  const state: PlayOverlayState = {
    isOpen: false,
    selectedLevel: 'play',
    activeActId: null,
    selectedSceneId: null,
    selectedBeatId: null,
    actsCache: [],
    scenesCache: [],
    beatsCache: [],
    kbText: '',
    kbPath: 'kb.md',
    attachments: [],
    expandedActs: new Set(),
    expandedScenes: new Set(),
  };

  // Create overlay container
  const overlay = el('div');
  overlay.className = 'play-overlay';

  const container = el('div');
  container.className = 'play-container';

  // Header
  const header = el('div');
  header.className = 'play-header';

  const headerTitle = el('h1');
  headerTitle.textContent = 'The Play';

  const closeBtn = el('button');
  closeBtn.className = 'play-close-btn';
  closeBtn.innerHTML = '&times;';
  closeBtn.addEventListener('click', close);

  header.appendChild(headerTitle);
  header.appendChild(closeBtn);

  // Body (sidebar + content)
  const body = el('div');
  body.className = 'play-body';

  const sidebar = el('div');
  sidebar.className = 'play-sidebar';

  const content = el('div');
  content.className = 'play-content';

  body.appendChild(sidebar);
  body.appendChild(content);

  container.appendChild(header);
  container.appendChild(body);
  overlay.appendChild(container);

  // Close on backdrop click
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      close();
    }
  });

  // Close on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && state.isOpen) {
      close();
    }
  });

  // --- Helper functions ---

  async function refreshData() {
    try {
      // Fetch acts
      const actsRes = (await kernelRequest('play/acts/list', {})) as PlayActsListResult;
      state.actsCache = actsRes.acts ?? [];
      state.activeActId = actsRes.active_act_id;

      // If we have an active act, auto-expand it
      if (state.activeActId) {
        state.expandedActs.add(state.activeActId);
      }

      // Fetch scenes if we have an active act
      if (state.activeActId) {
        const scenesRes = (await kernelRequest('play/scenes/list', {
          act_id: state.activeActId,
        })) as PlayScenesListResult;
        state.scenesCache = scenesRes.scenes ?? [];

        // If we have a selected scene, auto-expand it and fetch beats
        if (state.selectedSceneId) {
          state.expandedScenes.add(state.selectedSceneId);
          const beatsRes = (await kernelRequest('play/beats/list', {
            act_id: state.activeActId,
            scene_id: state.selectedSceneId,
          })) as PlayBeatsListResult;
          state.beatsCache = beatsRes.beats ?? [];
        } else {
          state.beatsCache = [];
        }
      } else {
        state.scenesCache = [];
        state.beatsCache = [];
      }

      // Fetch KB content for current selection
      await refreshKbContent();

      // Fetch attachments for current selection
      await refreshAttachments();
    } catch (e) {
      console.error('Failed to refresh Play data:', e);
    }
  }

  async function refreshKbContent() {
    if (!state.activeActId && state.selectedLevel !== 'play') {
      state.kbText = '';
      return;
    }

    try {
      if (state.selectedLevel === 'play') {
        // Read the Me file for play level
        const res = (await kernelRequest('play/me/read', {})) as { markdown: string };
        state.kbText = res.markdown ?? '';
      } else {
        const res = (await kernelRequest('play/kb/read', {
          act_id: state.activeActId,
          scene_id: state.selectedSceneId,
          beat_id: state.selectedBeatId,
          path: state.kbPath,
        })) as PlayKbReadResult;
        state.kbText = res.text ?? '';
      }
    } catch {
      // File doesn't exist yet, use empty
      state.kbText = '';
    }
  }

  async function refreshAttachments() {
    try {
      // For play level, pass no act_id; for others, pass the appropriate IDs
      const params: Record<string, string | null> = {};
      if (state.selectedLevel !== 'play' && state.activeActId) {
        params.act_id = state.activeActId;
        params.scene_id = state.selectedSceneId;
        params.beat_id = state.selectedBeatId;
      }
      const res = (await kernelRequest('play/attachments/list', params)) as PlayAttachmentsListResult;
      state.attachments = res.attachments ?? [];
    } catch {
      state.attachments = [];
    }
  }

  async function saveKbContent(text: string) {
    if (state.selectedLevel === 'play') {
      // Save play-level (me.md) through me/write endpoint
      try {
        await kernelRequest('play/me/write', { text });
        state.kbText = text;
      } catch (e) {
        console.error('Failed to save Play content:', e);
      }
      return;
    }

    if (!state.activeActId) return;

    try {
      // First preview
      const preview = (await kernelRequest('play/kb/write_preview', {
        act_id: state.activeActId,
        scene_id: state.selectedSceneId,
        beat_id: state.selectedBeatId,
        path: state.kbPath,
        text,
      })) as PlayKbWritePreviewResult;

      // Then apply
      await kernelRequest('play/kb/write_apply', {
        act_id: state.activeActId,
        scene_id: state.selectedSceneId,
        beat_id: state.selectedBeatId,
        path: state.kbPath,
        text,
        expected_sha256_current: preview.expected_sha256_current,
      });

      state.kbText = text;
    } catch (e) {
      console.error('Failed to save KB content:', e);
    }
  }

  async function handleAddAttachment() {
    try {
      const selected = await open({
        multiple: false,
        filters: [
          {
            name: 'Documents',
            extensions: ['pdf', 'doc', 'docx', 'txt', 'csv', 'xls', 'xlsx', 'md'],
          },
        ],
      });

      if (selected && typeof selected === 'string') {
        // For play level, pass no act_id; for others, pass the appropriate IDs
        const params: Record<string, string | null> = { file_path: selected };
        if (state.selectedLevel !== 'play' && state.activeActId) {
          params.act_id = state.activeActId;
          params.scene_id = state.selectedSceneId;
          params.beat_id = state.selectedBeatId;
        }
        await kernelRequest('play/attachments/add', params);

        await refreshAttachments();
        render();
      }
    } catch (e) {
      console.error('Failed to add attachment:', e);
    }
  }

  async function handleRemoveAttachment(attachmentId: string) {
    try {
      // For play level, pass no act_id; for others, pass the appropriate IDs
      const params: Record<string, string | null> = { attachment_id: attachmentId };
      if (state.selectedLevel !== 'play' && state.activeActId) {
        params.act_id = state.activeActId;
        params.scene_id = state.selectedSceneId;
        params.beat_id = state.selectedBeatId;
      }
      await kernelRequest('play/attachments/remove', params);

      await refreshAttachments();
      render();
    } catch (e) {
      console.error('Failed to remove attachment:', e);
    }
  }

  function deselectAct() {
    // Clear active act and go back to Play level
    state.activeActId = null;
    state.selectedSceneId = null;
    state.selectedBeatId = null;
    state.selectedLevel = 'play';
    state.scenesCache = [];
    state.beatsCache = [];

    void (async () => {
      // Tell backend to clear the active act
      await kernelRequest('play/acts/set_active', { act_id: null });
      await refreshKbContent();
      await refreshAttachments();
      render();
    })();
  }

  function selectLevel(
    level: PlayLevel,
    actId?: string | null,
    sceneId?: string | null,
    beatId?: string | null
  ) {
    state.selectedLevel = level;

    if (level === 'play') {
      state.selectedSceneId = null;
      state.selectedBeatId = null;
    } else if (level === 'act' && actId) {
      state.activeActId = actId;
      state.selectedSceneId = null;
      state.selectedBeatId = null;
      state.expandedActs.add(actId);
    } else if (level === 'scene' && actId && sceneId) {
      state.activeActId = actId;
      state.selectedSceneId = sceneId;
      state.selectedBeatId = null;
      state.expandedActs.add(actId);
      state.expandedScenes.add(sceneId);
    } else if (level === 'beat' && actId && sceneId && beatId) {
      state.activeActId = actId;
      state.selectedSceneId = sceneId;
      state.selectedBeatId = beatId;
      state.expandedActs.add(actId);
      state.expandedScenes.add(sceneId);
    }

    void (async () => {
      if (level === 'act' && actId) {
        // Set active act
        await kernelRequest('play/acts/set_active', { act_id: actId });
      }
      await refreshData();
      render();
    })();
  }

  function toggleActExpand(actId: string) {
    if (state.expandedActs.has(actId)) {
      state.expandedActs.delete(actId);
    } else {
      state.expandedActs.add(actId);
    }
    render();
  }

  function toggleSceneExpand(sceneId: string) {
    if (state.expandedScenes.has(sceneId)) {
      state.expandedScenes.delete(sceneId);
    } else {
      state.expandedScenes.add(sceneId);
    }
    render();
  }

  // Show color picker dropdown for an Act
  function showActColorPicker(actId: string, currentColor: string, anchorEl: HTMLElement) {
    // Remove any existing picker
    const existingPicker = document.querySelector('.act-color-picker');
    if (existingPicker) existingPicker.remove();

    const picker = el('div');
    picker.className = 'act-color-picker';
    picker.style.cssText = `
      position: fixed;
      background: #1e1e2e;
      border: 1px solid rgba(255,255,255,0.2);
      border-radius: 8px;
      padding: 8px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      z-index: 10000;
    `;

    // Position near the anchor
    const rect = anchorEl.getBoundingClientRect();
    picker.style.left = `${rect.left}px`;
    picker.style.top = `${rect.bottom + 4}px`;

    // Color grid
    const colorGrid = el('div');
    colorGrid.style.cssText = `
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 4px;
      margin-bottom: 8px;
    `;

    for (const color of ACT_COLOR_PALETTE) {
      const swatch = el('button');
      swatch.style.cssText = `
        width: 24px;
        height: 24px;
        border-radius: 4px;
        border: 2px solid ${color === currentColor ? '#fff' : 'transparent'};
        background: ${color};
        cursor: pointer;
        padding: 0;
      `;
      swatch.title = color;
      swatch.addEventListener('click', async () => {
        await updateActColor(actId, color);
        picker.remove();
      });
      colorGrid.appendChild(swatch);
    }
    picker.appendChild(colorGrid);

    // Custom hex input
    const customRow = el('div');
    customRow.style.cssText = `
      display: flex;
      gap: 4px;
      align-items: center;
    `;

    const hexInput = el('input') as HTMLInputElement;
    hexInput.type = 'text';
    hexInput.placeholder = '#hex';
    hexInput.value = currentColor;
    hexInput.style.cssText = `
      flex: 1;
      padding: 4px 6px;
      border-radius: 4px;
      border: 1px solid rgba(255,255,255,0.2);
      background: rgba(255,255,255,0.1);
      color: #fff;
      font-size: 12px;
      font-family: monospace;
    `;

    const applyBtn = el('button');
    applyBtn.textContent = '✓';
    applyBtn.style.cssText = `
      padding: 4px 8px;
      border-radius: 4px;
      border: none;
      background: #3b82f6;
      color: #fff;
      cursor: pointer;
      font-size: 12px;
    `;
    applyBtn.addEventListener('click', async () => {
      const val = hexInput.value.trim();
      if (/^#[0-9a-fA-F]{6}$/.test(val)) {
        await updateActColor(actId, val);
        picker.remove();
      } else {
        hexInput.style.borderColor = '#ef4444';
      }
    });

    customRow.appendChild(hexInput);
    customRow.appendChild(applyBtn);
    picker.appendChild(customRow);

    document.body.appendChild(picker);

    // Close picker on click outside
    const closeHandler = (e: MouseEvent) => {
      if (!picker.contains(e.target as Node) && e.target !== anchorEl) {
        picker.remove();
        document.removeEventListener('click', closeHandler);
      }
    };
    setTimeout(() => document.addEventListener('click', closeHandler), 0);
  }

  // Update Act color via RPC
  async function updateActColor(actId: string, color: string) {
    try {
      await kernelRequest('play/acts/update', { act_id: actId, color });
      await refreshData();
      render();
    } catch (e) {
      console.error('Failed to update Act color:', e);
    }
  }

  // --- Render functions ---

  function renderSidebar() {
    sidebar.innerHTML = '';

    // "The Play" root
    const playItem = el('div');
    playItem.className = `tree-item play ${state.selectedLevel === 'play' ? 'selected' : ''}`;
    playItem.innerHTML = '<span class="tree-icon">📘</span> The Play';
    playItem.addEventListener('click', () => selectLevel('play'));
    sidebar.appendChild(playItem);

    // Create new act button
    const newActBtn = el('button');
    newActBtn.className = 'tree-new-btn';
    newActBtn.textContent = '+ New Act';
    newActBtn.addEventListener('click', async () => {
      const title = prompt('Enter Act title:');
      if (title?.trim()) {
        await kernelRequest('play/acts/create', { title: title.trim() });
        await refreshData();
        render();
      }
    });
    sidebar.appendChild(newActBtn);

    // Acts (filter out "your-story" - it's represented by The Play root)
    for (const act of state.actsCache) {
      if (act.act_id === 'your-story') continue;

      const isExpanded = state.expandedActs.has(act.act_id);
      const isSelected = state.selectedLevel === 'act' && state.activeActId === act.act_id;
      const isActive = act.act_id === state.activeActId;

      const actItem = el('div');
      actItem.className = `tree-item act ${isSelected ? 'selected' : ''} ${isActive ? 'active' : ''}`;
      actItem.style.display = 'flex';
      actItem.style.alignItems = 'center';
      actItem.style.justifyContent = 'space-between';

      const actItemLeft = el('div');
      actItemLeft.style.display = 'flex';
      actItemLeft.style.alignItems = 'center';
      actItemLeft.style.flex = '1';
      actItemLeft.style.overflow = 'hidden';

      const expandIcon = el('span');
      expandIcon.className = 'tree-expand';
      expandIcon.textContent = isExpanded ? '▼' : '▶';
      expandIcon.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleActExpand(act.act_id);
      });

      const actLabel = el('span');
      actLabel.textContent = act.title;
      actLabel.style.overflow = 'hidden';
      actLabel.style.textOverflow = 'ellipsis';
      actLabel.style.whiteSpace = 'nowrap';

      actItemLeft.appendChild(expandIcon);
      actItemLeft.appendChild(actLabel);

      // Color picker button
      const colorBtn = el('button');
      colorBtn.className = 'act-color-btn';
      const actColor = act.color || '#8b5cf6';  // Default purple
      colorBtn.style.cssText = `
        width: 14px;
        height: 14px;
        border-radius: 3px;
        border: 1px solid rgba(255,255,255,0.3);
        background: ${actColor};
        cursor: pointer;
        flex-shrink: 0;
        margin-left: 4px;
        padding: 0;
      `;
      colorBtn.title = 'Change Act color';
      colorBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        showActColorPicker(act.act_id, actColor, colorBtn);
      });

      actItem.appendChild(actItemLeft);
      actItem.appendChild(colorBtn);
      actItemLeft.addEventListener('click', () => {
        // Toggle: if clicking already-active act, deselect it
        if (state.activeActId === act.act_id) {
          deselectAct();
        } else {
          selectLevel('act', act.act_id);
        }
      });
      sidebar.appendChild(actItem);

      // Scenes (if expanded and this is the active act)
      if (isExpanded && act.act_id === state.activeActId) {
        // New scene button
        const newSceneBtn = el('button');
        newSceneBtn.className = 'tree-new-btn scene-level';
        newSceneBtn.textContent = '+ New Scene';
        newSceneBtn.addEventListener('click', async () => {
          const title = prompt('Enter Scene title:');
          if (title?.trim()) {
            await kernelRequest('play/scenes/create', {
              act_id: act.act_id,
              title: title.trim(),
            });
            await refreshData();
            render();
          }
        });
        sidebar.appendChild(newSceneBtn);

        for (const scene of state.scenesCache) {
          const sceneExpanded = state.expandedScenes.has(scene.scene_id);
          const sceneSelected =
            state.selectedLevel === 'scene' && state.selectedSceneId === scene.scene_id;

          const sceneItem = el('div');
          sceneItem.className = `tree-item scene ${sceneSelected ? 'selected' : ''}`;

          const sceneExpandIcon = el('span');
          sceneExpandIcon.className = 'tree-expand';
          sceneExpandIcon.textContent = sceneExpanded ? '▼' : '▶';
          sceneExpandIcon.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleSceneExpand(scene.scene_id);
            // Also load beats when expanding
            if (!sceneExpanded) {
              void (async () => {
                const beatsRes = (await kernelRequest('play/beats/list', {
                  act_id: act.act_id,
                  scene_id: scene.scene_id,
                })) as PlayBeatsListResult;
                state.beatsCache = beatsRes.beats ?? [];
                render();
              })();
            }
          });

          const sceneLabel = el('span');
          sceneLabel.textContent = scene.title;

          sceneItem.appendChild(sceneExpandIcon);
          sceneItem.appendChild(sceneLabel);
          sceneItem.addEventListener('click', () =>
            selectLevel('scene', act.act_id, scene.scene_id)
          );
          sidebar.appendChild(sceneItem);

          // Beats (if scene is expanded and selected)
          if (sceneExpanded && state.selectedSceneId === scene.scene_id) {
            // New beat button
            const newBeatBtn = el('button');
            newBeatBtn.className = 'tree-new-btn beat-level';
            newBeatBtn.textContent = '+ New Beat';
            newBeatBtn.addEventListener('click', async () => {
              const title = prompt('Enter Beat title:');
              if (title?.trim()) {
                await kernelRequest('play/beats/create', {
                  act_id: act.act_id,
                  scene_id: scene.scene_id,
                  title: title.trim(),
                });
                await refreshData();
                render();
              }
            });
            sidebar.appendChild(newBeatBtn);

            for (const beat of state.beatsCache) {
              const beatSelected =
                state.selectedLevel === 'beat' && state.selectedBeatId === beat.beat_id;

              const beatItem = el('div');
              beatItem.className = `tree-item beat ${beatSelected ? 'selected' : ''}`;

              const bulletIcon = el('span');
              bulletIcon.className = 'tree-icon';
              bulletIcon.textContent = beat.stage === 'complete' ? '✓' : '•';
              beatItem.appendChild(bulletIcon);

              const beatTitle = el('span');
              beatTitle.textContent = ` ${beat.title}`;
              beatItem.appendChild(beatTitle);

              // Add stage badge
              if (beat.stage && beat.stage !== 'planning') {
                const stageBadge = el('span');
                stageBadge.className = `beat-stage beat-stage-${beat.stage}`;
                stageBadge.textContent = beat.stage.replace('_', ' ');
                beatItem.appendChild(stageBadge);
              }

              beatItem.addEventListener('click', () =>
                selectLevel('beat', act.act_id, scene.scene_id, beat.beat_id)
              );
              sidebar.appendChild(beatItem);
            }
          }
        }
      }
    }
  }

  function renderContent() {
    content.innerHTML = '';

    // Title based on selection
    const titleInput = el('input') as HTMLInputElement;
    titleInput.className = 'play-title-input';
    titleInput.placeholder = getLevelTitle();
    titleInput.value = getCurrentTitle();

    if (state.selectedLevel !== 'play') {
      titleInput.addEventListener('blur', async () => {
        const newTitle = titleInput.value.trim();
        if (!newTitle) return;
        await updateCurrentTitle(newTitle);
      });
    } else {
      titleInput.disabled = true;
    }

    content.appendChild(titleInput);

    // Repository Path (only for Acts, not for "your-story")
    if (state.selectedLevel === 'act' && state.activeActId && state.activeActId !== 'your-story') {
      const repoSection = el('div');
      repoSection.className = 'play-repo-section';
      repoSection.style.marginBottom = '16px';
      repoSection.style.padding = '12px';
      repoSection.style.background = 'rgba(255, 255, 255, 0.03)';
      repoSection.style.borderRadius = '8px';
      repoSection.style.border = '1px solid rgba(255, 255, 255, 0.1)';

      const repoLabel = el('div');
      repoLabel.textContent = 'Repository Path';
      repoLabel.style.fontSize = '11px';
      repoLabel.style.color = 'rgba(255, 255, 255, 0.5)';
      repoLabel.style.marginBottom = '8px';
      repoLabel.style.textTransform = 'uppercase';
      repoLabel.style.letterSpacing = '0.5px';

      const repoRow = el('div');
      repoRow.style.display = 'flex';
      repoRow.style.gap = '8px';
      repoRow.style.alignItems = 'center';

      // Find current act's repo_path
      const currentAct = state.actsCache.find(a => a.act_id === state.activeActId);

      const repoStatus = el('div');
      repoStatus.style.fontSize = '11px';
      repoStatus.style.marginTop = '6px';

      // Helper to assign repo
      const assignRepo = async (path: string) => {
        if (!path) {
          repoStatus.textContent = 'Please select or enter a path';
          repoStatus.style.color = '#ef4444';
          return;
        }
        try {
          repoStatus.textContent = 'Setting...';
          repoStatus.style.color = '#60a5fa';
          await kernelRequest('play/acts/assign_repo', {
            act_id: state.activeActId,
            repo_path: path,
          });
          await refreshData();
          render();
        } catch (e) {
          repoStatus.textContent = `Error: ${e}`;
          repoStatus.style.color = '#ef4444';
        }
      };

      // Text input for manual entry (defined first so browse can update it)
      const repoInput = el('input') as HTMLInputElement;
      repoInput.type = 'text';
      repoInput.placeholder = '/path/to/project';
      repoInput.style.flex = '2';
      repoInput.style.padding = '8px 12px';
      repoInput.style.background = 'rgba(0, 0, 0, 0.3)';
      repoInput.style.border = '1px solid rgba(255, 255, 255, 0.15)';
      repoInput.style.borderRadius = '6px';
      repoInput.style.color = '#fff';
      repoInput.style.fontSize = '13px';
      repoInput.value = currentAct?.repo_path ?? '';

      // Browse button (folder picker)
      const browseBtn = el('button');
      browseBtn.textContent = 'Browse...';
      browseBtn.style.padding = '8px 16px';
      browseBtn.style.background = 'rgba(59, 130, 246, 0.3)';
      browseBtn.style.border = '1px solid #3b82f6';
      browseBtn.style.borderRadius = '6px';
      browseBtn.style.color = '#60a5fa';
      browseBtn.style.fontSize = '12px';
      browseBtn.style.cursor = 'pointer';
      browseBtn.style.fontWeight = '500';
      browseBtn.style.flex = '1';

      browseBtn.addEventListener('click', async () => {
        try {
          const selected = await open({
            directory: true,
            multiple: false,
            title: 'Select Repository Folder',
          });
          if (selected && typeof selected === 'string') {
            repoInput.value = selected;  // Update text field immediately
            await assignRepo(selected);
          }
        } catch (e) {
          repoStatus.textContent = `Error: ${e}`;
          repoStatus.style.color = '#ef4444';
        }
      });

      // Or label
      const orLabel = el('span');
      orLabel.textContent = 'or';
      orLabel.style.color = 'rgba(255, 255, 255, 0.4)';
      orLabel.style.fontSize = '12px';

      // Set button for manual entry
      const repoBtn = el('button');
      repoBtn.textContent = 'Set';
      repoBtn.style.padding = '8px 12px';
      repoBtn.style.background = 'rgba(255, 255, 255, 0.1)';
      repoBtn.style.border = '1px solid rgba(255, 255, 255, 0.2)';
      repoBtn.style.borderRadius = '6px';
      repoBtn.style.color = 'rgba(255, 255, 255, 0.7)';
      repoBtn.style.fontSize = '12px';
      repoBtn.style.cursor = 'pointer';

      repoBtn.addEventListener('click', async () => {
        await assignRepo(repoInput.value.trim());
      });

      if (currentAct?.repo_path) {
        repoStatus.textContent = `Code Mode ready: ${currentAct.repo_path}`;
        repoStatus.style.color = '#22c55e';
      } else {
        repoStatus.textContent = 'No repository set. Required for Code Mode.';
        repoStatus.style.color = '#f59e0b';
      }

      repoRow.appendChild(browseBtn);
      repoRow.appendChild(orLabel);
      repoRow.appendChild(repoInput);
      repoRow.appendChild(repoBtn);
      repoSection.appendChild(repoLabel);
      repoSection.appendChild(repoRow);
      repoSection.appendChild(repoStatus);
      content.appendChild(repoSection);
    }

    // Editor area
    const editorWrap = el('div');
    editorWrap.className = 'play-editor-wrap';

    const editor = el('textarea') as HTMLTextAreaElement;
    editor.className = 'play-editor';
    editor.placeholder = PLACEHOLDER_TEXT[state.selectedLevel];
    editor.value = state.kbText;

    // Debounced auto-save
    let saveTimeout: ReturnType<typeof setTimeout> | null = null;
    editor.addEventListener('input', () => {
      if (saveTimeout) clearTimeout(saveTimeout);
      saveTimeout = setTimeout(() => {
        void saveKbContent(editor.value);
      }, 1500);
    });

    editorWrap.appendChild(editor);
    content.appendChild(editorWrap);

    // Attachments section (all levels including Play)
    const attachSection = el('div');
    attachSection.className = 'play-attachments';

    const attachHeader = el('div');
    attachHeader.className = 'attachments-header';

    const attachTitle = el('span');
    attachTitle.className = 'attachments-title';
    attachTitle.textContent = 'Attachments';

    const addBtn = el('button');
    addBtn.className = 'add-attachment-btn';
    addBtn.innerHTML = '<span>+</span> Add Document';
    addBtn.addEventListener('click', () => void handleAddAttachment());

    attachHeader.appendChild(attachTitle);
    attachHeader.appendChild(addBtn);
    attachSection.appendChild(attachHeader);

    const attachList = el('div');
    attachList.className = 'attachment-list';

    if (state.attachments.length === 0) {
      const emptyMsg = el('div');
      emptyMsg.className = 'attachment-empty';
      emptyMsg.textContent = state.selectedLevel === 'play'
        ? 'Attach your self-narrative, resume, or other identity documents'
        : 'No documents attached yet';
      attachList.appendChild(emptyMsg);
    } else {
      for (const att of state.attachments) {
        const pill = el('div');
        pill.className = 'attachment-pill';

        const icon = el('span');
        icon.className = `attachment-icon ${att.file_type}`;
        icon.textContent = att.file_type.toUpperCase().slice(0, 3);

        const name = el('span');
        name.className = 'attachment-name';
        name.textContent = att.file_name;
        name.title = att.file_path;

        const removeBtn = el('button');
        removeBtn.className = 'attachment-remove';
        removeBtn.innerHTML = '&times;';
        removeBtn.addEventListener('click', () => void handleRemoveAttachment(att.attachment_id));

        pill.appendChild(icon);
        pill.appendChild(name);
        pill.appendChild(removeBtn);
        attachList.appendChild(pill);
      }
    }

    attachSection.appendChild(attachList);
    content.appendChild(attachSection);
  }

  function getLevelTitle(): string {
    switch (state.selectedLevel) {
      case 'play':
        return 'The Play';
      case 'act':
        return 'Act Title';
      case 'scene':
        return 'Scene Title';
      case 'beat':
        return 'Beat Title';
    }
  }

  function getCurrentTitle(): string {
    switch (state.selectedLevel) {
      case 'play':
        return 'The Play';
      case 'act': {
        const act = state.actsCache.find((a) => a.act_id === state.activeActId);
        return act?.title ?? '';
      }
      case 'scene': {
        const scene = state.scenesCache.find((s) => s.scene_id === state.selectedSceneId);
        return scene?.title ?? '';
      }
      case 'beat': {
        const beat = state.beatsCache.find((b) => b.beat_id === state.selectedBeatId);
        return beat?.title ?? '';
      }
    }
  }

  async function updateCurrentTitle(newTitle: string) {
    try {
      switch (state.selectedLevel) {
        case 'act':
          if (state.activeActId) {
            await kernelRequest('play/acts/update', {
              act_id: state.activeActId,
              title: newTitle,
            });
          }
          break;
        case 'scene':
          if (state.activeActId && state.selectedSceneId) {
            await kernelRequest('play/scenes/update', {
              act_id: state.activeActId,
              scene_id: state.selectedSceneId,
              title: newTitle,
            });
          }
          break;
        case 'beat':
          if (state.activeActId && state.selectedSceneId && state.selectedBeatId) {
            await kernelRequest('play/beats/update', {
              act_id: state.activeActId,
              scene_id: state.selectedSceneId,
              beat_id: state.selectedBeatId,
              title: newTitle,
            });
          }
          break;
      }
      await refreshData();
      render();
    } catch (e) {
      console.error('Failed to update title:', e);
    }
  }

  function render() {
    renderSidebar();
    renderContent();
  }

  // --- Public API ---

  function openOverlay(actId?: string, sceneId?: string, beatId?: string) {
    state.isOpen = true;
    overlay.classList.add('open');

    // Set initial selection if provided
    if (beatId && sceneId && actId) {
      state.selectedLevel = 'beat';
      state.activeActId = actId;
      state.selectedSceneId = sceneId;
      state.selectedBeatId = beatId;
    } else if (sceneId && actId) {
      state.selectedLevel = 'scene';
      state.activeActId = actId;
      state.selectedSceneId = sceneId;
      state.selectedBeatId = null;
    } else if (actId) {
      state.selectedLevel = 'act';
      state.activeActId = actId;
      state.selectedSceneId = null;
      state.selectedBeatId = null;
    } else {
      state.selectedLevel = 'play';
    }

    void (async () => {
      await refreshData();
      render();
    })();
  }

  function close() {
    state.isOpen = false;
    overlay.classList.remove('open');
    onClose();
  }

  return {
    element: overlay,
    open: openOverlay,
    close,
  };
}
