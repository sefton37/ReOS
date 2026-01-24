/**
 * Play Kanban Board - Drag-and-drop Kanban component for Scenes
 *
 * Five columns representing scene stages:
 * - Planning (holding pen for unscheduled items)
 * - In Progress
 * - Awaiting Data
 * - Need Attention (overdue items that haven't been completed)
 * - Complete
 *
 * Card style matches the "What Needs Attention" pane in CAIRN.
 *
 * Planning column logic:
 * - Scenes with NO calendar event go to Planning
 * - Scenes scheduled for placeholder date (2099-12-31) go to Planning
 * - All other scenes use their actual stage
 *
 * Need Attention column logic:
 * - Scenes whose calendar date has passed but are not marked complete
 * - These require manual action to move to Complete
 */

import { el } from './dom';
import type { SceneWithAct, SceneStage, DisplayStage } from './types';

// Column definitions
const COLUMNS: { stage: DisplayStage; label: string; color: string; description: string }[] = [
  { stage: 'planning', label: 'Planning', color: '#9ca3af', description: 'Unscheduled items' },
  { stage: 'in_progress', label: 'In Progress', color: '#3b82f6', description: 'Active work' },
  { stage: 'awaiting_data', label: 'Awaiting Data', color: '#f59e0b', description: 'Blocked on info' },
  { stage: 'need_attention', label: 'Need Attention', color: '#ef4444', description: 'Overdue items' },
  { stage: 'complete', label: 'Complete', color: '#22c55e', description: 'Done' },
];

/**
 * Get the effective Kanban column for a scene.
 *
 * This is computed in the backend (play_computed.py) and returned as a field.
 * The frontend simply uses the pre-computed value.
 */
function getEffectiveStage(scene: SceneWithAct): DisplayStage {
  return scene.effective_stage;
}

// Sort options
type SortOption = 'date' | 'alpha' | 'act';

const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: 'date', label: 'Date' },
  { value: 'alpha', label: 'A-Z' },
  { value: 'act', label: 'Act' },
];

/**
 * Sort scenes by the given criteria.
 */
function sortScenes(scenes: SceneWithAct[], sortBy: SortOption): SceneWithAct[] {
  const sorted = [...scenes];

  switch (sortBy) {
    case 'date':
      sorted.sort((a, b) => {
        const dateA = a.next_occurrence || a.calendar_event_start || '';
        const dateB = b.next_occurrence || b.calendar_event_start || '';
        if (!dateA && !dateB) return 0;
        if (!dateA) return 1;
        if (!dateB) return -1;
        return new Date(dateA).getTime() - new Date(dateB).getTime();
      });
      break;

    case 'alpha':
      sorted.sort((a, b) => a.title.localeCompare(b.title));
      break;

    case 'act':
      sorted.sort((a, b) => {
        const actCompare = a.act_title.localeCompare(b.act_title);
        if (actCompare !== 0) return actCompare;
        // Secondary sort by title within same act
        return a.title.localeCompare(b.title);
      });
      break;
  }

  return sorted;
}

interface PlayKanbanBoardOptions {
  scenes: SceneWithAct[];
  onStageChange: (sceneId: string, newStage: SceneStage, actId: string) => Promise<void>;
  onSceneClick: (sceneId: string, actId: string) => void;
}

export function createPlayKanbanBoard(options: PlayKanbanBoardOptions): {
  element: HTMLElement;
} {
  const { scenes, onStageChange, onSceneClick } = options;

  // Current sort state
  let currentSort: SortOption = 'date';

  // Wrapper container (includes sort controls + board)
  const wrapper = el('div');
  wrapper.className = 'kanban-wrapper';
  wrapper.style.cssText = `
    display: flex;
    flex-direction: column;
    height: 100%;
  `;

  // Sort controls bar
  const sortBar = el('div');
  sortBar.className = 'kanban-sort-bar';
  sortBar.style.cssText = `
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    margin-bottom: 12px;
  `;

  const sortLabel = el('span');
  sortLabel.textContent = 'Sort by:';
  sortLabel.style.cssText = `
    font-size: 12px;
    color: rgba(255, 255, 255, 0.6);
  `;
  sortBar.appendChild(sortLabel);

  // Sort buttons
  const buttonContainer = el('div');
  buttonContainer.style.cssText = `
    display: flex;
    gap: 4px;
  `;

  const sortButtons: HTMLButtonElement[] = [];

  for (const opt of SORT_OPTIONS) {
    const btn = el('button') as HTMLButtonElement;
    btn.textContent = opt.label;
    btn.dataset.sort = opt.value;
    btn.style.cssText = `
      padding: 4px 12px;
      border-radius: 4px;
      border: 1px solid rgba(255, 255, 255, 0.2);
      background: ${opt.value === currentSort ? 'rgba(59, 130, 246, 0.3)' : 'rgba(0, 0, 0, 0.2)'};
      color: ${opt.value === currentSort ? '#60a5fa' : 'rgba(255, 255, 255, 0.7)'};
      font-size: 12px;
      cursor: pointer;
      transition: all 0.15s;
    `;

    btn.addEventListener('click', () => {
      currentSort = opt.value;
      updateSortButtons();
      rebuildBoard();
    });

    sortButtons.push(btn);
    buttonContainer.appendChild(btn);
  }

  sortBar.appendChild(buttonContainer);
  wrapper.appendChild(sortBar);

  // Update button styles based on current sort
  function updateSortButtons() {
    for (const btn of sortButtons) {
      const isActive = btn.dataset.sort === currentSort;
      btn.style.background = isActive ? 'rgba(59, 130, 246, 0.3)' : 'rgba(0, 0, 0, 0.2)';
      btn.style.color = isActive ? '#60a5fa' : 'rgba(255, 255, 255, 0.7)';
      btn.style.borderColor = isActive ? 'rgba(59, 130, 246, 0.5)' : 'rgba(255, 255, 255, 0.2)';
    }
  }

  // Board container
  const board = el('div');
  board.className = 'kanban-board';
  board.style.cssText = `
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    flex: 1;
    min-height: 400px;
  `;

  wrapper.appendChild(board);

  // Build/rebuild the board with current sort
  function rebuildBoard() {
    board.innerHTML = '';

    // Deduplicate recurring scenes - show each recurring scene only once
    const seenRecurringIds = new Set<string>();
    const deduplicatedScenes = scenes.filter(scene => {
      if (scene.recurrence_rule) {
        // For recurring scenes, use a composite key of act_id + title to dedupe
        const key = `${scene.act_id}:${scene.title}`;
        if (seenRecurringIds.has(key)) {
          return false;
        }
        seenRecurringIds.add(key);
      }
      return true;
    });

    // Group scenes by effective stage (using calendar date for Planning determination)
    const scenesByStage: Record<DisplayStage, SceneWithAct[]> = {
      planning: [],
      in_progress: [],
      awaiting_data: [],
      need_attention: [],
      complete: [],
    };

    for (const scene of deduplicatedScenes) {
      const effectiveStage = getEffectiveStage(scene);
      scenesByStage[effectiveStage].push(scene);
    }

    // Sort scenes in each column
    for (const stage of Object.keys(scenesByStage) as DisplayStage[]) {
      scenesByStage[stage] = sortScenes(scenesByStage[stage], currentSort);
    }

    // Create columns
    for (const column of COLUMNS) {
      const columnEl = createColumn(
        column,
        scenesByStage[column.stage],
        onStageChange,
        onSceneClick
      );
      board.appendChild(columnEl);
    }
  }

  // Initial build
  rebuildBoard();

  return {
    element: wrapper,
  };
}

function createColumn(
  column: { stage: DisplayStage; label: string; color: string; description: string },
  scenes: SceneWithAct[],
  onStageChange: (sceneId: string, newStage: SceneStage, actId: string) => Promise<void>,
  onSceneClick: (sceneId: string, actId: string) => void
): HTMLElement {
  const columnEl = el('div');
  columnEl.className = `kanban-column kanban-column-${column.stage}`;
  columnEl.dataset.stage = column.stage;
  columnEl.style.cssText = `
    display: flex;
    flex-direction: column;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 12px;
    overflow: hidden;
  `;

  // Column header
  const header = el('div');
  header.className = 'kanban-column-header';
  header.style.cssText = `
    padding: 12px 16px;
    background: ${column.color}22;
    border-bottom: 2px solid ${column.color};
  `;

  const headerTop = el('div');
  headerTop.style.cssText = `
    display: flex;
    align-items: center;
    justify-content: space-between;
  `;

  const headerTitle = el('span');
  headerTitle.textContent = column.label;
  headerTitle.style.cssText = `
    font-size: 13px;
    font-weight: 600;
    color: ${column.color};
  `;

  const headerCount = el('span');
  headerCount.textContent = String(scenes.length);
  headerCount.style.cssText = `
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    background: ${column.color}33;
    color: ${column.color};
  `;

  headerTop.appendChild(headerTitle);
  headerTop.appendChild(headerCount);
  header.appendChild(headerTop);

  // Description for planning column
  if (column.stage === 'planning') {
    const headerDesc = el('div');
    headerDesc.textContent = column.description;
    headerDesc.style.cssText = `
      font-size: 10px;
      color: rgba(255, 255, 255, 0.4);
      margin-top: 4px;
    `;
    header.appendChild(headerDesc);
  }

  columnEl.appendChild(header);

  // Cards container (drop zone)
  const cardsContainer = el('div');
  cardsContainer.className = 'kanban-cards';
  cardsContainer.dataset.stage = column.stage;
  cardsContainer.style.cssText = `
    flex: 1;
    padding: 12px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-height: 100px;
  `;

  // Drag and drop handlers
  cardsContainer.addEventListener('dragover', (e) => {
    e.preventDefault();
    cardsContainer.style.background = 'rgba(59, 130, 246, 0.1)';
    cardsContainer.style.outline = '2px dashed rgba(59, 130, 246, 0.5)';
    cardsContainer.style.outlineOffset = '-4px';
  });

  cardsContainer.addEventListener('dragleave', (e) => {
    // Only reset if leaving the container entirely
    if (!cardsContainer.contains(e.relatedTarget as Node)) {
      cardsContainer.style.background = 'transparent';
      cardsContainer.style.outline = 'none';
    }
  });

  cardsContainer.addEventListener('drop', async (e) => {
    e.preventDefault();
    cardsContainer.style.background = 'transparent';
    cardsContainer.style.outline = 'none';

    // Don't allow dropping onto 'need_attention' - it's a computed column
    // Items appear there automatically when overdue
    if (column.stage === 'need_attention') {
      return;
    }

    const sceneId = e.dataTransfer?.getData('scene_id');
    const actId = e.dataTransfer?.getData('act_id');
    const sourceStage = e.dataTransfer?.getData('source_stage');

    if (sceneId && actId && sourceStage !== column.stage) {
      await onStageChange(sceneId, column.stage as SceneStage, actId);
    }
  });

  // Add scene cards
  for (const scene of scenes) {
    const card = createSceneCard(scene, onSceneClick);
    cardsContainer.appendChild(card);
  }

  // Empty state
  if (scenes.length === 0) {
    const emptyState = el('div');
    emptyState.textContent = 'No scenes';
    emptyState.style.cssText = `
      text-align: center;
      padding: 24px;
      color: rgba(255, 255, 255, 0.3);
      font-size: 12px;
      font-style: italic;
    `;
    cardsContainer.appendChild(emptyState);
  }

  columnEl.appendChild(cardsContainer);

  return columnEl;
}

/**
 * Get urgency level based on scene properties.
 * This matches the CAIRN attention surfacing logic.
 */
function getUrgency(scene: SceneWithAct): 'critical' | 'high' | 'medium' | 'low' {
  // Scenes in progress are high priority
  if (scene.stage === 'in_progress') {
    return 'high';
  }
  // Scenes awaiting data need attention
  if (scene.stage === 'awaiting_data') {
    return 'medium';
  }
  // Planning items are low priority
  if (scene.stage === 'planning') {
    return 'low';
  }
  // Complete items are low
  return 'low';
}

function getUrgencyColor(urgency: string): string {
  switch (urgency) {
    case 'critical': return '#ef4444';
    case 'high': return '#f97316';
    case 'medium': return '#eab308';
    default: return '#22c55e';
  }
}

function createSceneCard(
  scene: SceneWithAct,
  onSceneClick: (sceneId: string, actId: string) => void
): HTMLElement {
  const card = el('div');
  card.className = 'kanban-card';
  card.draggable = true;
  card.dataset.sceneId = scene.scene_id;
  card.dataset.actId = scene.act_id;

  const actColor = scene.act_color || '#8b5cf6';
  const urgency = getUrgency(scene);
  const urgencyColor = getUrgencyColor(urgency);
  const isRecurring = !!scene.recurrence_rule;

  // Match CAIRN "What Needs Attention" card style exactly
  card.style.cssText = `
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 8px;
    cursor: grab;
    transition: background 0.2s;
  `;

  // Drag handlers
  card.addEventListener('dragstart', (e) => {
    card.style.opacity = '0.5';
    card.style.cursor = 'grabbing';
    e.dataTransfer?.setData('scene_id', scene.scene_id);
    e.dataTransfer?.setData('act_id', scene.act_id);
    e.dataTransfer?.setData('source_stage', scene.stage);
  });

  card.addEventListener('dragend', () => {
    card.style.opacity = '1';
    card.style.cursor = 'grab';
  });

  // Click handler
  card.addEventListener('click', () => {
    onSceneClick(scene.scene_id, scene.act_id);
  });

  // Hover effect (matches CAIRN)
  card.addEventListener('mouseenter', () => {
    card.style.background = 'rgba(255, 255, 255, 0.08)';
  });

  card.addEventListener('mouseleave', () => {
    card.style.background = 'rgba(255, 255, 255, 0.05)';
  });

  // Title row with urgency dot, title, recurring icon, and act label (matches CAIRN exactly)
  const titleRow = el('div');
  titleRow.style.cssText = `
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
  `;

  // Urgency dot
  const urgencyDot = el('span');
  urgencyDot.style.cssText = `
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: ${urgencyColor};
    flex-shrink: 0;
  `;

  // Title
  const title = el('span');
  title.textContent = scene.title;
  title.style.cssText = `
    font-weight: 500;
    color: #fff;
    font-size: 13px;
  `;

  titleRow.appendChild(urgencyDot);
  titleRow.appendChild(title);

  // Recurring icon (inline with title, matches CAIRN)
  if (isRecurring) {
    const recurringIcon = el('span');
    recurringIcon.textContent = '🔄';
    recurringIcon.title = `Recurring: ${scene.recurrence_rule}`;
    recurringIcon.style.cssText = `
      font-size: 11px;
      margin-left: 4px;
    `;
    titleRow.appendChild(recurringIcon);
  }

  // Act label (inline with title, matches CAIRN style)
  const actLabel = el('span');
  actLabel.textContent = `Act: ${scene.act_title}`;
  actLabel.style.cssText = `
    font-size: 10px;
    margin-left: 6px;
    padding: 2px 6px;
    background: ${actColor}33;
    color: ${actColor};
    border-radius: 4px;
  `;
  titleRow.appendChild(actLabel);

  card.appendChild(titleRow);

  // Date/reason row (matches CAIRN style exactly)
  const reasonText = formatSceneReason(scene);
  if (reasonText) {
    const reasonRow = el('div');
    reasonRow.textContent = reasonText;
    reasonRow.style.cssText = `
      font-size: 12px;
      color: rgba(255, 255, 255, 0.5);
      padding-left: 16px;
    `;
    card.appendChild(reasonRow);
  }

  return card;
}

/**
 * Format the "reason" text for a scene card (matches CAIRN surfacing format).
 * Shows date/time like "Jan 14, Wednesday at 9:30 AM" or relative time if soon.
 */
function formatSceneReason(scene: SceneWithAct): string {
  // Use next_occurrence for recurring events, otherwise calendar_event_start
  const dateStr = scene.next_occurrence || scene.calendar_event_start;

  if (!dateStr) {
    // No date - show notes if available, otherwise empty
    if (scene.notes && scene.notes.trim()) {
      return scene.notes.slice(0, 80) + (scene.notes.length > 80 ? '...' : '');
    }
    return '';
  }

  try {
    const eventTime = new Date(dateStr);
    const now = new Date();
    const diffMs = eventTime.getTime() - now.getTime();
    const diffMinutes = Math.round(diffMs / 60000);

    if (diffMinutes <= 0 && diffMinutes > -60) {
      return 'Happening now';
    } else if (diffMinutes > 0 && diffMinutes < 60) {
      return `In ${diffMinutes} minutes`;
    } else if (diffMinutes >= 60 && diffMinutes < 120) {
      const hours = Math.floor(diffMinutes / 60);
      const mins = diffMinutes % 60;
      return `In ${hours}h ${mins}m`;
    } else {
      // Format as "Jan 14, Wednesday at 9:30 AM"
      const dayName = eventTime.toLocaleDateString('en-US', { weekday: 'long' });
      const monthDay = eventTime.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      const time = eventTime.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
      return `${monthDay}, ${dayName} at ${time}`;
    }
  } catch {
    // Invalid date
    return scene.notes?.slice(0, 80) || '';
  }
}
