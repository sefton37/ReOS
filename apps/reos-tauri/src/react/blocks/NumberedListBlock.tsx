/**
 * NumberedListBlock - Renders a numbered list item with optional nested children.
 */

import type { Block } from '../types';
import { RichTextContent } from './RichTextContent';
import { BlockRenderer } from './BlockRenderer';

interface NumberedListBlockProps {
  block: Block;
  onUpdate?: (block: Block) => void;
  onDelete?: (blockId: string) => void;
  isEditing?: boolean;
  depth?: number;
}

export function NumberedListBlock({
  block,
  onUpdate,
  onDelete,
  isEditing = false,
  depth = 0,
}: NumberedListBlockProps) {
  const hasChildren = block.children && block.children.length > 0;

  // The position is used as the list number (1-indexed for display)
  const listNumber = (block.position ?? 0) + 1;

  return (
    <div style={{ margin: '0.2em 0' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: '8px',
        }}
      >
        <span
          style={{
            color: 'rgba(255, 255, 255, 0.5)',
            fontSize: '14px',
            lineHeight: 1.7,
            minWidth: '20px',
            textAlign: 'right',
          }}
        >
          {listNumber}.
        </span>
        <div style={{ flex: 1, color: '#e5e7eb', fontSize: '14px', lineHeight: 1.7 }}>
          <RichTextContent spans={block.rich_text} />
        </div>
      </div>

      {hasChildren && (
        <div style={{ paddingLeft: '28px', marginTop: '4px' }}>
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
  );
}

export default NumberedListBlock;
