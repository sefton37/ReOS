/**
 * Play Kanban Board - Drag-and-drop Kanban component for Scenes
 *
 * Four columns representing scene stages:
 * - Planning (holding pen for unscheduled items)
 * - In Progress
 * - Awaiting Data
 * - Complete
 *
 * Card style matches the "What Needs Attention" pane in CAIRN.
 *
 * Planning column logic:
 * - Scenes with NO calendar event go to Planning
 * - Scenes scheduled for placeholder date (2099-12-31) go to Planning
 * - All other scenes use their actual stage
 */

import { el } from './dom';
import type { SceneWithAct, SceneStage } from './types';

// Column definitions
const COLUMNS: { stage: SceneStage; label: string; color: string; description: string }[] = [
  { stage: 'planning', label: 'Planning', color: '#9ca3af', description: 'Unscheduled items' },
  { stage: 'in_progress', label: 'In Progress', color: '#3b82f6', description: 'Active work' },
  { stage: 'awaiting_data', label: 'Awaiting Data', color: '#f59e0b', description: 'Blocked on info' },
  { stage: 'complete', label: 'Complete', color: '#22c55e', description: 'Done' },
];

/**
 * Check if a date is the placeholder date (December 31 of current year).
 * The placeholder is used for manually created scenes that haven't been scheduled.
 */
function isPlaceholderDate(date: Date): boolean {
  const currentYear = new Date().getFullYear();
  return date.getMonth() === 11 && date.getDate() === 31 && date.getFullYear() === currentYear;
}

/**
 * Determine if a scene is "unscheduled" (belongs in Planning column).
 *
 * A scene is unscheduled if:
 * 1. It has no calendar_event_start AND no thunderbird_event_id, OR
 * 2. Its calendar_event_start is the placeholder date (Dec 31 of current year)
 */
function isUnscheduled(scene: SceneWithAct): boolean {
  // Use next_occurrence for recurring events, otherwise calendar_event_start
  const eventDate = scene.next_occurrence || scene.calendar_event_start;

  // No calendar event at all
  if (!eventDate && !scene.thunderbird_event_id) {
    return true;
  }

  // Check if scheduled for placeholder date (Dec 31 of current year)
  if (eventDate) {
    try {
      const date = new Date(eventDate);
      if (isPlaceholderDate(date)) {
        return true;
      }
    } catch {
      // Invalid date, treat as unscheduled
      return true;
    }
  }

  return false;
}

/**
 * Get the effective Kanban column for a scene.
 *
 * Unscheduled items always go to Planning.
 * Scheduled items use their actual stage, but 'planning' becomes 'in_progress'
 * since having a date means the work is scheduled/active.
 */
function getEffectiveStage(scene: SceneWithAct): SceneStage {
  // Unscheduled items always go to Planning
  if (isUnscheduled(scene)) {
    return 'planning';
  }

  // Completed items stay in Complete regardless of scheduling
  if (scene.stage === 'complete') {
    return 'complete';
  }

  // For scheduled items, 'planning' stage becomes 'in_progress' since they have a date
  // (Planning column is only for unscheduled items)
  if (scene.stage === 'planning') {
    return 'in_progress';
  }

  // For other scheduled items, use actual stage
  return (scene.stage as SceneStage) || 'in_progress';
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

  // Main container
  const board = el('div');
  board.className = 'kanban-board';
  board.style.cssText = `
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    height: 100%;
    min-height: 400px;
  `;

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
  const scenesByStage: Record<SceneStage, SceneWithAct[]> = {
    planning: [],
    in_progress: [],
    awaiting_data: [],
    complete: [],
  };

  for (const scene of deduplicatedScenes) {
    const effectiveStage = getEffectiveStage(scene);
    scenesByStage[effectiveStage].push(scene);
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

  return {
    element: board,
  };
}

function createColumn(
  column: { stage: SceneStage; label: string; color: string; description: string },
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

    const sceneId = e.dataTransfer?.getData('scene_id');
    const actId = e.dataTransfer?.getData('act_id');
    const sourceStage = e.dataTransfer?.getData('source_stage');

    if (sceneId && actId && sourceStage !== column.stage) {
      await onStageChange(sceneId, column.stage, actId);
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
