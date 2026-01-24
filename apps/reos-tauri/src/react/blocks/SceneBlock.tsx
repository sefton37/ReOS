/**
 * SceneBlock - Renders an embedded scene (calendar event) block.
 */

import type { Block } from '../types';

interface SceneBlockProps {
  block: Block;
  onUpdate?: (block: Block) => void;
  onDelete?: (blockId: string) => void;
  isEditing?: boolean;
  depth?: number;
}

// Scene stage colors
const STAGE_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  planning: { bg: 'rgba(59, 130, 246, 0.1)', text: '#60a5fa', label: 'Planning' },
  in_progress: { bg: 'rgba(245, 158, 11, 0.1)', text: '#fbbf24', label: 'In Progress' },
  awaiting_data: { bg: 'rgba(139, 92, 246, 0.1)', text: '#a78bfa', label: 'Awaiting' },
  complete: { bg: 'rgba(34, 197, 94, 0.1)', text: '#22c55e', label: 'Complete' },
};

export function SceneBlock({
  block,
  onUpdate,
  isEditing = false,
}: SceneBlockProps) {
  const title = block.rich_text.map((span) => span.content).join('') || 'Untitled Scene';
  const sceneId = block.scene_id;
  const stage = (block.properties.stage as string) || 'planning';
  const scheduledAt = block.properties.scheduled_at as string | null;
  const isRecurring = Boolean(block.properties.is_recurring);

  const stageInfo = STAGE_COLORS[stage] || STAGE_COLORS.planning;

  // Format date if available
  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return 'Unscheduled';
    try {
      const date = new Date(dateStr);
      return date.toLocaleDateString('en-US', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      });
    } catch {
      return 'Unscheduled';
    }
  };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '12px 16px',
        background: stageInfo.bg,
        borderRadius: '8px',
        border: '1px solid rgba(255, 255, 255, 0.1)',
        margin: '0.5em 0',
        cursor: 'pointer',
        transition: 'background 0.15s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'rgba(255, 255, 255, 0.1)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = stageInfo.bg;
      }}
    >
      {/* Calendar icon */}
      <span
        style={{
          fontSize: '18px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '32px',
          height: '32px',
          background: 'rgba(255, 255, 255, 0.1)',
          borderRadius: '6px',
        }}
      >
        📅
      </span>

      {/* Scene info */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span
            style={{
              color: '#f3f4f6',
              fontSize: '14px',
              fontWeight: 500,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {title}
          </span>
          {isRecurring && (
            <span
              style={{
                fontSize: '12px',
                color: 'rgba(255, 255, 255, 0.5)',
              }}
              title="Recurring"
            >
              🔄
            </span>
          )}
        </div>
        <div
          style={{
            color: 'rgba(255, 255, 255, 0.5)',
            fontSize: '12px',
            marginTop: '2px',
          }}
        >
          {formatDate(scheduledAt)}
        </div>
      </div>

      {/* Stage badge */}
      <span
        style={{
          padding: '4px 8px',
          background: stageInfo.bg,
          color: stageInfo.text,
          fontSize: '11px',
          fontWeight: 500,
          borderRadius: '4px',
          border: `1px solid ${stageInfo.text}33`,
        }}
      >
        {stageInfo.label}
      </span>
    </div>
  );
}

export default SceneBlock;
