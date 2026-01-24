/**
 * PageLinkPopover - Autocomplete dropdown for page links.
 * Shows matching pages when user types [[.
 */

import { useState, useEffect, useCallback, forwardRef, useImperativeHandle } from 'react';

export interface PageItem {
  page_id: string;
  title: string;
  icon?: string;
  act_title?: string;
}

interface PageLinkPopoverProps {
  query: string;
  items: PageItem[];
  onSelect: (item: PageItem) => void;
  onClose: () => void;
}

export interface PageLinkPopoverHandle {
  onKeyDown: (event: KeyboardEvent) => boolean;
}

export const PageLinkPopover = forwardRef<PageLinkPopoverHandle, PageLinkPopoverProps>(
  function PageLinkPopover({ query, items, onSelect, onClose }, ref) {
    const [selectedIndex, setSelectedIndex] = useState(0);

    // Reset selection when items change
    useEffect(() => {
      setSelectedIndex(0);
    }, [items]);

    const selectItem = useCallback(
      (index: number) => {
        const item = items[index];
        if (item) {
          onSelect(item);
        }
      },
      [items, onSelect],
    );

    // Expose keyboard handler to parent
    useImperativeHandle(
      ref,
      () => ({
        onKeyDown: (event: KeyboardEvent) => {
          if (event.key === 'ArrowDown') {
            event.preventDefault();
            setSelectedIndex((prev) => (prev + 1) % items.length);
            return true;
          }

          if (event.key === 'ArrowUp') {
            event.preventDefault();
            setSelectedIndex((prev) => (prev - 1 + items.length) % items.length);
            return true;
          }

          if (event.key === 'Enter') {
            event.preventDefault();
            selectItem(selectedIndex);
            return true;
          }

          if (event.key === 'Escape') {
            event.preventDefault();
            onClose();
            return true;
          }

          return false;
        },
      }),
      [items, selectedIndex, selectItem, onClose],
    );

    if (items.length === 0) {
      return (
        <div
          style={{
            background: '#1f1f23',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '8px',
            boxShadow: '0 4px 20px rgba(0, 0, 0, 0.4)',
            padding: '12px',
            minWidth: '200px',
          }}
        >
          <div
            style={{
              color: 'rgba(255, 255, 255, 0.4)',
              fontSize: '12px',
              textAlign: 'center',
            }}
          >
            {query ? 'No matching pages' : 'Type to search pages...'}
          </div>
        </div>
      );
    }

    return (
      <div
        style={{
          background: '#1f1f23',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          borderRadius: '8px',
          boxShadow: '0 4px 20px rgba(0, 0, 0, 0.4)',
          padding: '4px',
          minWidth: '240px',
          maxWidth: '320px',
          maxHeight: '300px',
          overflowY: 'auto',
        }}
      >
        {items.map((item, index) => (
          <button
            key={item.page_id}
            onClick={() => selectItem(index)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              width: '100%',
              padding: '8px 12px',
              border: 'none',
              background: index === selectedIndex ? 'rgba(34, 197, 94, 0.15)' : 'transparent',
              borderRadius: '6px',
              cursor: 'pointer',
              textAlign: 'left',
              transition: 'background 0.1s',
            }}
            onMouseEnter={(e) => {
              if (index !== selectedIndex) {
                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
              }
              setSelectedIndex(index);
            }}
            onMouseLeave={(e) => {
              if (index !== selectedIndex) {
                e.currentTarget.style.background = 'transparent';
              }
            }}
          >
            <span style={{ fontSize: '14px' }}>{item.icon || '📄'}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  color: index === selectedIndex ? '#22c55e' : '#f3f4f6',
                  fontSize: '13px',
                  fontWeight: 500,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {item.title}
              </div>
              {item.act_title && (
                <div
                  style={{
                    color: 'rgba(255, 255, 255, 0.4)',
                    fontSize: '11px',
                    marginTop: '1px',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  in {item.act_title}
                </div>
              )}
            </div>
          </button>
        ))}
      </div>
    );
  },
);

export default PageLinkPopover;
