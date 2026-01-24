/**
 * CalloutBlock - Renders a callout block with icon and optional background color.
 */

import type { Block } from '../types';
import { RichTextContent } from './RichTextContent';
import { BlockRenderer } from './BlockRenderer';

interface CalloutBlockProps {
  block: Block;
  onUpdate?: (block: Block) => void;
  onDelete?: (blockId: string) => void;
  isEditing?: boolean;
  depth?: number;
}

// Default callout colors
const CALLOUT_COLORS: Record<string, { bg: string; border: string }> = {
  gray: { bg: 'rgba(255, 255, 255, 0.05)', border: 'rgba(255, 255, 255, 0.2)' },
  blue: { bg: 'rgba(59, 130, 246, 0.1)', border: 'rgba(59, 130, 246, 0.3)' },
  green: { bg: 'rgba(34, 197, 94, 0.1)', border: 'rgba(34, 197, 94, 0.3)' },
  yellow: { bg: 'rgba(245, 158, 11, 0.1)', border: 'rgba(245, 158, 11, 0.3)' },
  red: { bg: 'rgba(239, 68, 68, 0.1)', border: 'rgba(239, 68, 68, 0.3)' },
  purple: { bg: 'rgba(139, 92, 246, 0.1)', border: 'rgba(139, 92, 246, 0.3)' },
};

export function CalloutBlock({
  block,
  onUpdate,
  onDelete,
  isEditing = false,
  depth = 0,
}: CalloutBlockProps) {
  const icon = (block.properties.icon as string) || '💡';
  const colorName = (block.properties.color as string) || 'gray';
  const colors = CALLOUT_COLORS[colorName] || CALLOUT_COLORS.gray;
  const hasChildren = block.children && block.children.length > 0;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: '12px',
        padding: '16px',
        background: colors.bg,
        borderLeft: `3px solid ${colors.border}`,
        borderRadius: '0 8px 8px 0',
        margin: '0.5em 0',
      }}
    >
      <span
        style={{
          fontSize: '20px',
          lineHeight: 1,
        }}
      >
        {icon}
      </span>
      <div style={{ flex: 1 }}>
        <div
          style={{
            color: '#e5e7eb',
            fontSize: '14px',
            lineHeight: 1.7,
          }}
        >
          <RichTextContent spans={block.rich_text} />
        </div>

        {hasChildren && (
          <div style={{ marginTop: '8px' }}>
            {block.children.map((child) => (
              <BlockRenderer
                key={child.id}
                block={child}
                onUpdate={onUpdate}
                onDelete={onDelete}
                isEditing={isEditing}
                depth={depth + 1}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default CalloutBlock;
