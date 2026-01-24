/**
 * TodosView - Shows all unchecked todos grouped by act.
 */

import { useState, useEffect, useMemo } from 'react';
import type { Block } from '../types';

interface Act {
  act_id: string;
  title: string;
  color?: string;
}

interface TodosViewProps {
  kernelRequest: (method: string, params: Record<string, unknown>) => Promise<unknown>;
  onNavigateToBlock?: (blockId: string, actId: string, pageId: string | null) => void;
  onToggleTodo?: (blockId: string, checked: boolean) => void;
}

export function TodosView({
  kernelRequest,
  onNavigateToBlock,
  onToggleTodo,
}: TodosViewProps) {
  const [todos, setTodos] = useState<Block[]>([]);
  const [acts, setActs] = useState<Act[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | string>('all');

  useEffect(() => {
    async function loadData() {
      setLoading(true);

      try {
        // Load acts for grouping
        const actsResult = (await kernelRequest('play/acts/list', {})) as {
          acts: Act[];
        };
        setActs(actsResult.acts ?? []);

        // Load unchecked todos
        const todosResult = (await kernelRequest('blocks/unchecked_todos', {})) as {
          blocks: Block[];
        };
        setTodos(todosResult.blocks ?? []);
      } catch (error) {
        console.error('Failed to load todos:', error);
        setTodos([]);
        setActs([]);
      } finally {
        setLoading(false);
      }
    }

    void loadData();
  }, [kernelRequest]);

  // Group todos by act
  const groupedTodos = useMemo(() => {
    const groups = new Map<string, Block[]>();

    for (const todo of todos) {
      const actId = todo.act_id;
      if (!groups.has(actId)) {
        groups.set(actId, []);
      }
      groups.get(actId)!.push(todo);
    }

    return groups;
  }, [todos]);

  // Filter todos by act
  const filteredGroups = useMemo(() => {
    if (filter === 'all') {
      return groupedTodos;
    }
    const filtered = new Map<string, Block[]>();
    const actTodos = groupedTodos.get(filter);
    if (actTodos) {
      filtered.set(filter, actTodos);
    }
    return filtered;
  }, [groupedTodos, filter]);

  const getActInfo = (actId: string): Act | undefined => {
    return acts.find((a) => a.act_id === actId);
  };

  const handleToggle = async (todo: Block) => {
    if (onToggleTodo) {
      onToggleTodo(todo.id, true);
      // Optimistically remove from list
      setTodos((prev) => prev.filter((t) => t.id !== todo.id));
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '24px', color: 'rgba(255, 255, 255, 0.5)' }}>
        Loading...
      </div>
    );
  }

  return (
    <div style={{ padding: '24px' }}>
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '24px',
        }}
      >
        <h2
          style={{
            fontSize: '20px',
            fontWeight: 600,
            color: '#f3f4f6',
          }}
        >
          Todos ({todos.length})
        </h2>

        {/* Filter dropdown */}
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{
            padding: '6px 12px',
            background: 'rgba(255, 255, 255, 0.05)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '6px',
            color: '#e5e7eb',
            fontSize: '13px',
            cursor: 'pointer',
          }}
        >
          <option value="all">All Acts</option>
          {acts
            .filter((a) => a.act_id !== 'your-story' && groupedTodos.has(a.act_id))
            .map((act) => (
              <option key={act.act_id} value={act.act_id}>
                {act.title}
              </option>
            ))}
        </select>
      </div>

      {todos.length === 0 && (
        <div
          style={{
            padding: '32px',
            textAlign: 'center',
            color: 'rgba(255, 255, 255, 0.4)',
            background: 'rgba(255, 255, 255, 0.03)',
            borderRadius: '12px',
          }}
        >
          <div style={{ fontSize: '32px', marginBottom: '8px' }}>✅</div>
          <div>All caught up!</div>
        </div>
      )}

      {/* Grouped todos */}
      {Array.from(filteredGroups.entries()).map(([actId, actTodos]) => {
        const actInfo = getActInfo(actId);

        return (
          <div key={actId} style={{ marginBottom: '24px' }}>
            {/* Act header */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                marginBottom: '12px',
              }}
            >
              <span
                style={{
                  width: '10px',
                  height: '10px',
                  borderRadius: '50%',
                  background: actInfo?.color || '#8b5cf6',
                }}
              />
              <span
                style={{
                  color: 'rgba(255, 255, 255, 0.7)',
                  fontSize: '14px',
                  fontWeight: 500,
                }}
              >
                {actInfo?.title || 'Unknown Act'}
              </span>
              <span
                style={{
                  color: 'rgba(255, 255, 255, 0.3)',
                  fontSize: '12px',
                }}
              >
                ({actTodos.length})
              </span>
            </div>

            {/* Todo items */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {actTodos.map((todo) => (
                <div
                  key={todo.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px',
                    padding: '10px 16px',
                    background: 'rgba(255, 255, 255, 0.03)',
                    border: '1px solid rgba(255, 255, 255, 0.1)',
                    borderRadius: '8px',
                    cursor: 'pointer',
                    transition: 'background 0.15s',
                  }}
                  onClick={() =>
                    onNavigateToBlock?.(todo.id, todo.act_id, todo.page_id)
                  }
                >
                  <input
                    type="checkbox"
                    checked={false}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleToggle(todo);
                    }}
                    style={{
                      width: '16px',
                      height: '16px',
                      accentColor: '#22c55e',
                      cursor: 'pointer',
                    }}
                  />
                  <span
                    style={{
                      flex: 1,
                      color: '#e5e7eb',
                      fontSize: '13px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {todo.rich_text.map((s) => s.content).join('') || 'Untitled todo'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default TodosView;
