/**
 * CodeBlock - Renders a code block with optional language highlighting.
 */

import type { Block } from '../types';

interface CodeBlockProps {
  block: Block;
  onUpdate?: (block: Block) => void;
  onDelete?: (blockId: string) => void;
  isEditing?: boolean;
  depth?: number;
}

export function CodeBlock({
  block,
  onUpdate,
  isEditing = false,
}: CodeBlockProps) {
  const language = (block.properties.language as string) || 'text';
  const code = block.rich_text.map((span) => span.content).join('');

  return (
    <div style={{ margin: '0.5em 0' }}>
      {language !== 'text' && (
        <div
          style={{
            fontSize: '11px',
            color: 'rgba(255, 255, 255, 0.4)',
            marginBottom: '4px',
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          }}
        >
          {language}
        </div>
      )}
      <pre
        style={{
          background: 'rgba(0, 0, 0, 0.4)',
          padding: '12px 16px',
          borderRadius: '8px',
          overflowX: 'auto',
          margin: 0,
        }}
      >
        <code
          style={{
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            fontSize: '0.85em',
            lineHeight: 1.5,
            color: '#e5e7eb',
          }}
        >
          {code || ' '}
        </code>
      </pre>
    </div>
  );
}

export default CodeBlock;
