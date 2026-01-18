/**
 * Play Scene View - Kanban board of all Scenes, filterable by Act
 *
 * Shows all scenes across acts in a 4-column Kanban board:
 * - Planning
 * - In Progress
 * - Awaiting Data
 * - Complete
 *
 * Scene cards are color-coded by their parent Act.
 */

import { el } from './dom';
import { createPlayKanbanBoard } from './playKanbanBoard';
import type {
  PlayActsListResult,
  SceneWithAct,
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

interface PlaySceneViewState {
  actsCache: PlayActsListResult['acts'];
  scenesCache: SceneWithAct[];
  enabledActs: Set<string>;
}

interface PlaySceneViewOptions {
  onSceneChange: () => Promise<void>;
  kernelRequest: (method: string, params: Record<string, unknown>) => Promise<unknown>;
}

export function createPlaySceneView(options: PlaySceneViewOptions): {
  element: HTMLElement;
  refresh: () => void;
} {
  const { onSceneChange, kernelRequest } = options;

  const state: PlaySceneViewState = {
    actsCache: [],
    scenesCache: [],
    enabledActs: new Set(),
  };

  // Main container
  const container = el('div');
  container.className = 'play-scene-view';
  container.style.cssText = `
    display: flex;
    flex-direction: column;
    flex: 1;
    overflow: hidden;
  `;

  // Filter bar
  const filterBar = el('div');
  filterBar.className = 'scene-filter-bar';
  filterBar.style.cssText = `
    padding: 12px 24px;
    background: rgba(0, 0, 0, 0.2);
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  `;

  const filterLabel = el('span');
  filterLabel.textContent = 'Filter:';
  filterLabel.style.cssText = `
    font-size: 12px;
    color: rgba(255, 255, 255, 0.6);
    margin-right: 4px;
  `;
  filterBar.appendChild(filterLabel);

  // Kanban board area
  const boardArea = el('div');
  boardArea.className = 'kanban-board-area';
  boardArea.style.cssText = `
    flex: 1;
    overflow: auto;
    padding: 16px 24px;
  `;

  container.appendChild(filterBar);
  container.appendChild(boardArea);

  // Create Kanban board
  let kanbanBoard: ReturnType<typeof createPlayKanbanBoard> | null = null;

  // --- Data Loading ---

  async function loadData() {
    try {
      // Load acts
      const actsResult = await kernelRequest('play/acts/list', {}) as PlayActsListResult;
      state.actsCache = actsResult.acts ?? [];

      // Enable all acts by default (including your-story)
      for (const act of state.actsCache) {
        state.enabledActs.add(act.act_id);
      }

      // Load all scenes
      await loadAllScenes();
    } catch (e) {
      console.error('Failed to load data:', e);
    }
  }

  async function loadAllScenes() {
    try {
      const result = await kernelRequest('play/scenes/list_all', {}) as { scenes: SceneWithAct[] };
      state.scenesCache = result.scenes ?? [];
    } catch {
      // Endpoint may not exist yet - fall back to loading scenes per act
      state.scenesCache = [];
      for (const act of state.actsCache) {
        try {
          const result = await kernelRequest('play/scenes/list', { act_id: act.act_id }) as { scenes: Array<{ scene_id: string; act_id: string; title: string; stage: string; notes: string }> };
          const actScenes = (result.scenes ?? []).map(s => ({
            ...s,
            act_title: act.title,
            act_color: act.color || ACT_COLOR_PALETTE[0],
          }));
          state.scenesCache.push(...actScenes);
        } catch {
          // Skip this act
        }
      }
    }
  }

  // --- Rendering ---

  function renderFilterBar() {
    // Clear filter buttons (keep label)
    while (filterBar.children.length > 1) {
      filterBar.removeChild(filterBar.lastChild!);
    }

    for (const act of state.actsCache) {
      const isEnabled = state.enabledActs.has(act.act_id);
      const actColor = act.color || ACT_COLOR_PALETTE[0];

      const filterChip = el('button');
      filterChip.className = 'act-filter-chip';
      filterChip.style.cssText = `
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 12px;
        border-radius: 16px;
        border: 1px solid ${isEnabled ? actColor : 'rgba(255, 255, 255, 0.2)'};
        background: ${isEnabled ? `${actColor}33` : 'transparent'};
        color: ${isEnabled ? actColor : 'rgba(255, 255, 255, 0.5)'};
        cursor: pointer;
        font-size: 12px;
        font-weight: 500;
        transition: all 0.2s;
      `;

      // Color dot
      const colorDot = el('span');
      colorDot.style.cssText = `
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: ${actColor};
        opacity: ${isEnabled ? '1' : '0.4'};
      `;

      // Label
      const label = el('span');
      label.textContent = act.title;

      // Toggle indicator
      const indicator = el('span');
      indicator.textContent = isEnabled ? '●' : '○';
      indicator.style.cssText = `
        font-size: 8px;
        margin-left: 2px;
      `;

      filterChip.appendChild(colorDot);
      filterChip.appendChild(label);
      filterChip.appendChild(indicator);

      filterChip.addEventListener('click', () => {
        if (state.enabledActs.has(act.act_id)) {
          state.enabledActs.delete(act.act_id);
        } else {
          state.enabledActs.add(act.act_id);
        }
        render();
      });

      filterChip.addEventListener('mouseenter', () => {
        filterChip.style.background = `${actColor}44`;
      });
      filterChip.addEventListener('mouseleave', () => {
        filterChip.style.background = isEnabled ? `${actColor}33` : 'transparent';
      });

      filterBar.appendChild(filterChip);
    }
  }

  function renderBoard() {
    boardArea.innerHTML = '';

    // Filter scenes by enabled acts
    const filteredScenes = state.scenesCache.filter(
      scene => state.enabledActs.has(scene.act_id)
    );

    // Create or update kanban board
    kanbanBoard = createPlayKanbanBoard({
      scenes: filteredScenes,
      onStageChange: async (sceneId, newStage, actId) => {
        try {
          await kernelRequest('play/scenes/update', {
            act_id: actId,
            scene_id: sceneId,
            stage: newStage,
          });
          await loadAllScenes();
          await onSceneChange();
          render();
        } catch (e) {
          console.error('Failed to update scene stage:', e);
        }
      },
      onSceneClick: (sceneId, actId) => {
        void showSceneDetail(sceneId, actId);
      },
    });

    boardArea.appendChild(kanbanBoard.element);
  }

  async function showSceneDetail(sceneId: string, actId: string) {
    // For now, show a simple modal. In the future, this could open a detail panel.
    const scene = state.scenesCache.find(s => s.scene_id === sceneId);
    if (!scene) return;

    const modal = el('div');
    modal.className = 'scene-detail-modal';
    modal.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0, 0, 0, 0.8);
      backdrop-filter: blur(8px);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1000;
    `;

    const content = el('div');
    content.style.cssText = `
      background: #1e1e2e;
      border-radius: 16px;
      padding: 24px;
      max-width: 600px;
      width: 90%;
      max-height: 80vh;
      overflow-y: auto;
      border: 1px solid rgba(255, 255, 255, 0.1);
    `;

    // Header
    const header = el('div');
    header.style.cssText = `
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 16px;
    `;

    const title = el('h2');
    title.textContent = scene.title;
    title.style.cssText = `
      margin: 0;
      font-size: 20px;
      color: #e5e7eb;
    `;

    const closeBtn = el('button');
    closeBtn.innerHTML = '&times;';
    closeBtn.style.cssText = `
      width: 32px;
      height: 32px;
      border-radius: 8px;
      border: none;
      background: rgba(255, 255, 255, 0.1);
      color: #e5e7eb;
      cursor: pointer;
      font-size: 20px;
    `;
    closeBtn.addEventListener('click', () => modal.remove());

    header.appendChild(title);
    header.appendChild(closeBtn);
    content.appendChild(header);

    // Act badge
    const actBadge = el('div');
    actBadge.textContent = scene.act_title;
    actBadge.style.cssText = `
      display: inline-block;
      padding: 4px 12px;
      border-radius: 12px;
      background: ${scene.act_color}33;
      color: ${scene.act_color};
      font-size: 12px;
      font-weight: 500;
      margin-bottom: 16px;
    `;
    content.appendChild(actBadge);

    // Stage selector
    const stageSection = el('div');
    stageSection.style.marginBottom = '16px';

    const stageLabel = el('div');
    stageLabel.textContent = 'Stage';
    stageLabel.style.cssText = `
      font-size: 11px;
      color: rgba(255, 255, 255, 0.5);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 8px;
    `;

    const stageSelect = el('select') as HTMLSelectElement;
    stageSelect.style.cssText = `
      width: 100%;
      padding: 8px 12px;
      border-radius: 8px;
      border: 1px solid rgba(255, 255, 255, 0.2);
      background: rgba(0, 0, 0, 0.3);
      color: #e5e7eb;
      font-size: 14px;
    `;

    const stages = [
      { value: 'planning', label: 'Planning' },
      { value: 'in_progress', label: 'In Progress' },
      { value: 'awaiting_data', label: 'Awaiting Data' },
      { value: 'complete', label: 'Complete' },
    ];

    for (const s of stages) {
      const option = el('option') as HTMLOptionElement;
      option.value = s.value;
      option.textContent = s.label;
      option.selected = scene.stage === s.value;
      option.style.cssText = 'background: #1a1a2e; color: #e5e7eb;';
      stageSelect.appendChild(option);
    }

    stageSelect.addEventListener('change', async () => {
      try {
        await kernelRequest('play/scenes/update', {
          act_id: actId,
          scene_id: sceneId,
          stage: stageSelect.value,
        });
        await loadAllScenes();
        await onSceneChange();
        render();
      } catch (e) {
        console.error('Failed to update stage:', e);
      }
    });

    stageSection.appendChild(stageLabel);
    stageSection.appendChild(stageSelect);
    content.appendChild(stageSection);

    // Notes
    const notesSection = el('div');

    const notesLabel = el('div');
    notesLabel.textContent = 'Notes';
    notesLabel.style.cssText = `
      font-size: 11px;
      color: rgba(255, 255, 255, 0.5);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 8px;
    `;

    const notesTextarea = el('textarea') as HTMLTextAreaElement;
    notesTextarea.value = scene.notes || '';
    notesTextarea.placeholder = 'Add notes...';
    notesTextarea.style.cssText = `
      width: 100%;
      min-height: 150px;
      padding: 12px;
      border-radius: 8px;
      border: 1px solid rgba(255, 255, 255, 0.1);
      background: rgba(0, 0, 0, 0.2);
      color: #e5e7eb;
      font-size: 14px;
      line-height: 1.6;
      resize: vertical;
    `;

    let saveTimeout: ReturnType<typeof setTimeout> | null = null;
    notesTextarea.addEventListener('input', () => {
      if (saveTimeout) clearTimeout(saveTimeout);
      saveTimeout = setTimeout(async () => {
        try {
          await kernelRequest('play/scenes/update', {
            act_id: actId,
            scene_id: sceneId,
            notes: notesTextarea.value,
          });
          await loadAllScenes();
        } catch (e) {
          console.error('Failed to save notes:', e);
        }
      }, 1000);
    });

    notesSection.appendChild(notesLabel);
    notesSection.appendChild(notesTextarea);
    content.appendChild(notesSection);

    modal.appendChild(content);

    // Close on backdrop click
    modal.addEventListener('click', (e) => {
      if (e.target === modal) modal.remove();
    });

    // Close on Escape
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        modal.remove();
        document.removeEventListener('keydown', handleEscape);
      }
    };
    document.addEventListener('keydown', handleEscape);

    document.body.appendChild(modal);
  }

  function render() {
    renderFilterBar();
    renderBoard();
  }

  async function refresh() {
    await loadData();
    render();
  }

  // Initial load
  void refresh();

  return {
    element: container,
    refresh,
  };
}
