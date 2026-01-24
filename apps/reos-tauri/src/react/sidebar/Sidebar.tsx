/**
 * Sidebar - Enhanced sidebar component with act/page tree navigation.
 * This is a React version of the sidebar for use in the block editor.
 */

import { useState, useCallback, useEffect } from 'react';

// Color palette for Acts (matches Python ACT_COLOR_PALETTE)
const ACT_COLOR_PALETTE = [
  '#8b5cf6', // Purple
  '#3b82f6', // Blue
  '#10b981', // Green
  '#f59e0b', // Amber
  '#ef4444', // Red
  '#ec4899', // Pink
  '#06b6d4', // Cyan
  '#84cc16', // Lime
  '#f97316', // Orange
  '#6366f1', // Indigo
  '#14b8a6', // Teal
  '#a855f7', // Fuchsia
];

export interface Act {
  act_id: string;
  title: string;
  color?: string;
}

export interface Page {
  page_id: string;
  title: string;
  icon?: string;
  children?: Page[];
}

interface SidebarProps {
  acts: Act[];
  pages: Map<string, Page[]>;
  activeActId: string | null;
  selectedPageId: string | null;
  onSelectPlay: () => void;
  onSelectAct: (actId: string) => void;
  onSelectPage: (actId: string, pageId: string) => void;
  onCreateAct: () => void;
  onCreatePage: (actId: string) => void;
  onLoadPages: (actId: string) => void;
}

export function Sidebar({
  acts,
  pages,
  activeActId,
  selectedPageId,
  onSelectPlay,
  onSelectAct,
  onSelectPage,
  onCreateAct,
  onCreatePage,
  onLoadPages,
}: SidebarProps) {
  const [expandedActs, setExpandedActs] = useState<Set<string>>(new Set());
  const [expandedPages, setExpandedPages] = useState<Set<string>>(new Set());

  // Auto-expand active act
  useEffect(() => {
    if (activeActId) {
      setExpandedActs((prev) => new Set(prev).add(activeActId));
    }
  }, [activeActId]);

  const toggleActExpand = useCallback(
    (actId: string) => {
      setExpandedActs((prev) => {
        const next = new Set(prev);
        if (next.has(actId)) {
          next.delete(actId);
        } else {
          next.add(actId);
          onLoadPages(actId);
        }
        return next;
      });
    },
    [onLoadPages],
  );

  const togglePageExpand = useCallback((pageId: string) => {
    setExpandedPages((prev) => {
      const next = new Set(prev);
      if (next.has(pageId)) {
        next.delete(pageId);
      } else {
        next.add(pageId);
      }
      return next;
    });
  }, []);

  const renderPageTree = (pageList: Page[], actId: string, depth: number) => {
    return pageList.map((page) => {
      const isExpanded = expandedPages.has(page.page_id);
      const isSelected = selectedPageId === page.page_id;
      const hasChildren = page.children && page.children.length > 0;
      const indent = depth * 16;

      return (
        <div key={page.page_id}>
          <button
            onClick={() => onSelectPage(actId, page.page_id)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              width: '100%',
              padding: '6px 12px',
              paddingLeft: `${12 + indent}px`,
              border: 'none',
              borderRadius: '6px',
              background: isSelected ? 'rgba(59, 130, 246, 0.2)' : 'transparent',
              color: isSelected ? '#60a5fa' : 'rgba(255, 255, 255, 0.7)',
              cursor: 'pointer',
              fontSize: '12px',
              textAlign: 'left',
              transition: 'background 0.15s',
            }}
          >
            {hasChildren ? (
              <span
                onClick={(e) => {
                  e.stopPropagation();
                  togglePageExpand(page.page_id);
                }}
                style={{
                  width: '12px',
                  fontSize: '8px',
                  opacity: 0.5,
                  cursor: 'pointer',
                }}
              >
                {isExpanded ? '▼' : '▶'}
              </span>
            ) : (
              <span style={{ width: '12px' }} />
            )}
            <span style={{ fontSize: '12px' }}>{page.icon || '📄'}</span>
            <span
              style={{
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {page.title}
            </span>
          </button>

          {isExpanded && hasChildren && renderPageTree(page.children!, actId, depth + 1)}
        </div>
      );
    });
  };

  return (
    <div
      style={{
        width: '280px',
        minWidth: '280px',
        borderRight: '1px solid rgba(255, 255, 255, 0.1)',
        overflowY: 'auto',
        padding: '16px',
        background: 'rgba(0, 0, 0, 0.15)',
      }}
    >
      {/* The Play root */}
      <button
        onClick={onSelectPlay}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          width: '100%',
          padding: '8px 12px',
          border: 'none',
          borderRadius: '8px',
          background:
            !activeActId && !selectedPageId ? 'rgba(34, 197, 94, 0.2)' : 'transparent',
          color: !activeActId && !selectedPageId ? '#22c55e' : 'rgba(255, 255, 255, 0.8)',
          cursor: 'pointer',
          fontSize: '13px',
          textAlign: 'left',
          marginBottom: '8px',
          transition: 'background 0.15s',
        }}
      >
        <span style={{ fontSize: '14px' }}>📘</span>
        The Play
      </button>

      {/* New Act button */}
      <button
        onClick={onCreateAct}
        style={{
          width: '100%',
          padding: '6px 12px',
          marginBottom: '12px',
          border: '1px dashed rgba(255, 255, 255, 0.2)',
          borderRadius: '6px',
          background: 'transparent',
          color: 'rgba(255, 255, 255, 0.5)',
          cursor: 'pointer',
          fontSize: '12px',
          textAlign: 'left',
          transition: 'all 0.15s',
        }}
      >
        + New Act
      </button>

      {/* Acts list */}
      {acts
        .filter((act) => act.act_id !== 'your-story')
        .map((act) => {
          const isExpanded = expandedActs.has(act.act_id);
          const isSelected = activeActId === act.act_id && !selectedPageId;
          const actColor = act.color || ACT_COLOR_PALETTE[0];
          const actPages = pages.get(act.act_id) || [];

          return (
            <div key={act.act_id}>
              <button
                onClick={() => onSelectAct(act.act_id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  width: '100%',
                  padding: '8px 12px',
                  border: 'none',
                  borderRadius: '8px',
                  background: isSelected ? 'rgba(34, 197, 94, 0.2)' : 'transparent',
                  color: isSelected ? '#22c55e' : 'rgba(255, 255, 255, 0.8)',
                  cursor: 'pointer',
                  fontSize: '13px',
                  textAlign: 'left',
                  marginBottom: '2px',
                  transition: 'background 0.15s',
                }}
              >
                <span
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleActExpand(act.act_id);
                  }}
                  style={{
                    width: '16px',
                    fontSize: '10px',
                    opacity: 0.6,
                    cursor: 'pointer',
                  }}
                >
                  {isExpanded ? '▼' : '▶'}
                </span>
                <span
                  style={{
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    background: actColor,
                    flexShrink: 0,
                  }}
                />
                <span
                  style={{
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    flex: 1,
                  }}
                >
                  {act.title}
                </span>
              </button>

              {isExpanded && (
                <>
                  {renderPageTree(actPages, act.act_id, 1)}

                  <button
                    onClick={() => onCreatePage(act.act_id)}
                    style={{
                      width: 'calc(100% - 24px)',
                      marginLeft: '24px',
                      padding: '4px 12px',
                      marginBottom: '8px',
                      border: '1px dashed rgba(255, 255, 255, 0.15)',
                      borderRadius: '6px',
                      background: 'transparent',
                      color: 'rgba(255, 255, 255, 0.4)',
                      cursor: 'pointer',
                      fontSize: '11px',
                      textAlign: 'left',
                      transition: 'all 0.15s',
                    }}
                  >
                    + New Page
                  </button>
                </>
              )}
            </div>
          );
        })}
    </div>
  );
}

export default Sidebar;
