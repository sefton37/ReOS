/**
 * TodoBlock - Renders a to-do item with checkbox and optional nested children.
 */

import type { Block } from '../types';
import { RichTextContent } from './RichTextContent';
import { BlockRenderer } from './BlockRenderer';

interface TodoBlockProps {
  block: Block;
  onUpdate?: (block: Block) => void;
  onDelete?: (blockId: string) => void;
  isEditing?: boolean;
  depth?: number;
}

export function TodoBlock({
  block,
  onUpdate,
  onDelete,
  isEditing = false,
  depth = 0,
}: TodoBlockProps) {
  const isChecked = Boolean(block.properties.checked);
  const hasChildren = block.children && block.children.length > 0;

  const handleToggle = () => {
    if (onUpdate) {
      onUpdate({
        ...block,
        properties: {
          ...block.properties,
          checked: !isChecked,
        },
      });
    }
  };

  return (
    <div style={{ margin: '0.2em 0' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: '8px',
        }}
      >
        <input
          type="checkbox"
          checked={isChecked}
          onChange={handleToggle}
          style={{
            width: '16px',
            height: '16px',
            marginTop: '4px',
            cursor: 'pointer',
            accentColor: '#22c55e',
          }}
        />
        <div
          style={{
            flex: 1,
            color: '#e5e7eb',
            fontSize: '14px',
            lineHeight: 1.7,
            textDecoration: isChecked ? 'line-through' : 'none',
            opacity: isChecked ? 0.6 : 1,
          }}
        >
          <RichTextContent spans={block.rich_text} />
        </div>
      </div>

      {hasChildren && (
        <div style={{ paddingLeft: '24px', marginTop: '4px' }}>
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

export default TodoBlock;
