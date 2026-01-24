/**
 * SearchResults - Displays search results with highlighted matches.
 */

import type { Block } from '../types';

interface SearchResult {
  block: Block;
  context: string;
  matchStart: number;
  matchEnd: number;
}

interface SearchResultsProps {
  results: SearchResult[];
  selectedIndex: number;
  onSelect: (block: Block) => void;
  onHover: (index: number) => void;
}

// Block type icons
const BLOCK_TYPE_ICONS: Record<string, string> = {
  paragraph: '📝',
  heading_1: 'H1',
  heading_2: 'H2',
  heading_3: 'H3',
  bulleted_list: '•',
  numbered_list: '1.',
  to_do: '☑️',
  code: '</>',
  callout: '💡',
  scene: '📅',
  page: '📄',
};

export function SearchResults({
  results,
  selectedIndex,
  onSelect,
  onHover,
}: SearchResultsProps) {
  if (results.length === 0) {
    return null;
  }

  return (
    <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
      {results.map((result, index) => {
        const isSelected = index === selectedIndex;
        const icon = BLOCK_TYPE_ICONS[result.block.type] || '📝';

        // Highlight the match in context
        const beforeMatch = result.context.slice(0, result.matchStart);
        const match = result.context.slice(result.matchStart, result.matchEnd);
        const afterMatch = result.context.slice(result.matchEnd);

        return (
          <button
            key={result.block.id}
            onClick={() => onSelect(result.block)}
            onMouseEnter={() => onHover(index)}
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: '12px',
              width: '100%',
              padding: '12px 16px',
              border: 'none',
              borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
              background: isSelected ? 'rgba(34, 197, 94, 0.1)' : 'transparent',
              cursor: 'pointer',
              textAlign: 'left',
              transition: 'background 0.1s',
            }}
          >
            {/* Block type icon */}
            <span
              style={{
                width: '24px',
                height: '24px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'rgba(255, 255, 255, 0.1)',
                borderRadius: '4px',
                fontSize: '12px',
                color: 'rgba(255, 255, 255, 0.7)',
                flexShrink: 0,
              }}
            >
              {icon}
            </span>

            <div style={{ flex: 1, minWidth: 0 }}>
              {/* Context with highlighted match */}
              <div
                style={{
                  color: '#e5e7eb',
                  fontSize: '13px',
                  lineHeight: 1.5,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {beforeMatch}
                <mark
                  style={{
                    background: 'rgba(245, 158, 11, 0.3)',
                    color: '#fbbf24',
                    padding: '0 2px',
                    borderRadius: '2px',
                  }}
                >
                  {match}
                </mark>
                {afterMatch}
              </div>

              {/* Block type label */}
              <div
                style={{
                  color: 'rgba(255, 255, 255, 0.4)',
                  fontSize: '11px',
                  marginTop: '4px',
                  textTransform: 'capitalize',
                }}
              >
                {result.block.type.replace('_', ' ')}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export default SearchResults;
