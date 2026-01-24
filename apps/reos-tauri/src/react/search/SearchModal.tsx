/**
 * SearchModal - Global search modal triggered by Cmd+K.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type { Block } from '../types';
import { useSearch } from './useSearch';
import { SearchResults } from './SearchResults';

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  kernelRequest: (method: string, params: Record<string, unknown>) => Promise<unknown>;
  onNavigateToBlock?: (block: Block) => void;
}

export function SearchModal({
  isOpen,
  onClose,
  kernelRequest,
  onNavigateToBlock,
}: SearchModalProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const { query, setQuery, results, isLoading } = useSearch({
    kernelRequest,
    debounceMs: 200,
  });

  // Focus input when modal opens
  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedIndex(0);
      // Delay focus to ensure modal is rendered
      setTimeout(() => {
        inputRef.current?.focus();
      }, 0);
    }
  }, [isOpen, setQuery]);

  // Reset selection when results change
  useEffect(() => {
    setSelectedIndex(0);
  }, [results]);

  // Handle keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setSelectedIndex((prev) => Math.min(prev + 1, results.length - 1));
          break;

        case 'ArrowUp':
          e.preventDefault();
          setSelectedIndex((prev) => Math.max(prev - 1, 0));
          break;

        case 'Enter':
          e.preventDefault();
          if (results[selectedIndex]) {
            onNavigateToBlock?.(results[selectedIndex].block);
            onClose();
          }
          break;

        case 'Escape':
          e.preventDefault();
          onClose();
          break;
      }
    },
    [results, selectedIndex, onNavigateToBlock, onClose],
  );

  const handleSelect = useCallback(
    (block: Block) => {
      onNavigateToBlock?.(block);
      onClose();
    },
    [onNavigateToBlock, onClose],
  );

  if (!isOpen) {
    return null;
  }

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0, 0, 0, 0.6)',
          backdropFilter: 'blur(4px)',
          zIndex: 9999,
        }}
      />

      {/* Modal */}
      <div
        style={{
          position: 'fixed',
          top: '15%',
          left: '50%',
          transform: 'translateX(-50%)',
          width: '100%',
          maxWidth: '600px',
          background: '#1f1f23',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          borderRadius: '12px',
          boxShadow: '0 20px 60px rgba(0, 0, 0, 0.5)',
          zIndex: 10000,
          overflow: 'hidden',
        }}
      >
        {/* Search input */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            padding: '16px',
            borderBottom: '1px solid rgba(255, 255, 255, 0.1)',
          }}
        >
          <span style={{ fontSize: '18px', opacity: 0.5 }}>🔍</span>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search blocks..."
            style={{
              flex: 1,
              border: 'none',
              background: 'transparent',
              color: '#e5e7eb',
              fontSize: '16px',
              outline: 'none',
            }}
          />
          {isLoading && (
            <span
              style={{
                color: 'rgba(255, 255, 255, 0.4)',
                fontSize: '12px',
              }}
            >
              Searching...
            </span>
          )}
          <kbd
            style={{
              padding: '2px 6px',
              background: 'rgba(255, 255, 255, 0.1)',
              borderRadius: '4px',
              fontSize: '11px',
              color: 'rgba(255, 255, 255, 0.4)',
            }}
          >
            ESC
          </kbd>
        </div>

        {/* Results */}
        {query.trim() ? (
          results.length > 0 ? (
            <SearchResults
              results={results}
              selectedIndex={selectedIndex}
              onSelect={handleSelect}
              onHover={setSelectedIndex}
            />
          ) : !isLoading ? (
            <div
              style={{
                padding: '32px',
                textAlign: 'center',
                color: 'rgba(255, 255, 255, 0.4)',
              }}
            >
              No results found for "{query}"
            </div>
          ) : null
        ) : (
          <div
            style={{
              padding: '32px',
              textAlign: 'center',
              color: 'rgba(255, 255, 255, 0.4)',
            }}
          >
            <div style={{ fontSize: '24px', marginBottom: '8px' }}>🔍</div>
            <div>Type to search across all blocks</div>
          </div>
        )}

        {/* Footer with keyboard shortcuts */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '16px',
            padding: '12px',
            borderTop: '1px solid rgba(255, 255, 255, 0.1)',
            background: 'rgba(0, 0, 0, 0.2)',
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <kbd
              style={{
                padding: '2px 6px',
                background: 'rgba(255, 255, 255, 0.1)',
                borderRadius: '4px',
                fontSize: '10px',
                color: 'rgba(255, 255, 255, 0.5)',
              }}
            >
              ↑↓
            </kbd>
            <span style={{ fontSize: '11px', color: 'rgba(255, 255, 255, 0.4)' }}>
              Navigate
            </span>
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <kbd
              style={{
                padding: '2px 6px',
                background: 'rgba(255, 255, 255, 0.1)',
                borderRadius: '4px',
                fontSize: '10px',
                color: 'rgba(255, 255, 255, 0.5)',
              }}
            >
              ↵
            </kbd>
            <span style={{ fontSize: '11px', color: 'rgba(255, 255, 255, 0.4)' }}>
              Open
            </span>
          </span>
        </div>
      </div>
    </>
  );
}

export default SearchModal;
