/**
 * TodayView - Shows scenes due today and unchecked todos.
 */

import { useState, useEffect } from 'react';
import type { Block } from '../types';

interface Scene {
  scene_id: string;
  title: string;
  act_id: string;
  act_title?: string;
  stage: string;
  scheduled_at: string | null;
  is_recurring: boolean;
}

interface TodayViewProps {
  kernelRequest: (method: string, params: Record<string, unknown>) => Promise<unknown>;
  onNavigateToScene?: (sceneId: string) => void;
  onNavigateToBlock?: (blockId: string, actId: string, pageId: string | null) => void;
}

export function TodayView({
  kernelRequest,
  onNavigateToScene,
  onNavigateToBlock,
}: TodayViewProps) {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [todos, setTodos] = useState<Block[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      setLoading(true);

      try {
        // Load scenes due today
        const scenesResult = (await kernelRequest('play/scenes/list_all', {})) as {
          scenes: Scene[];
        };
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const tomorrow = new Date(today);
        tomorrow.setDate(tomorrow.getDate() + 1);

        const todayScenes = (scenesResult.scenes ?? []).filter((scene) => {
          if (!scene.scheduled_at) return false;
          const date = new Date(scene.scheduled_at);
          return date >= today && date < tomorrow;
        });
        setScenes(todayScenes);

        // Load unchecked todos
        const todosResult = (await kernelRequest('blocks/unchecked_todos', {})) as {
          blocks: Block[];
        };
        setTodos(todosResult.blocks ?? []);
      } catch (error) {
        console.error('Failed to load today view:', error);
        setScenes([]);
        setTodos([]);
      } finally {
        setLoading(false);
      }
    }

    void loadData();
  }, [kernelRequest]);

  const formatTime = (dateStr: string | null): string => {
    if (!dateStr) return '';
    try {
      const date = new Date(dateStr);
      return date.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
      });
    } catch {
      return '';
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '24px', color: 'rgba(255, 255, 255, 0.5)' }}>
        Loading...
      </div>
    );
  }

  const hasContent = scenes.length > 0 || todos.length > 0;

  return (
    <div style={{ padding: '24px' }}>
      <h2
        style={{
          fontSize: '20px',
          fontWeight: 600,
          color: '#f3f4f6',
          marginBottom: '24px',
        }}
      >
        Today
      </h2>

      {!hasContent && (
        <div
          style={{
            padding: '32px',
            textAlign: 'center',
            color: 'rgba(255, 255, 255, 0.4)',
            background: 'rgba(255, 255, 255, 0.03)',
            borderRadius: '12px',
          }}
        >
          <div style={{ fontSize: '32px', marginBottom: '8px' }}>🎯</div>
          <div>Nothing scheduled for today</div>
        </div>
      )}

      {/* Scenes */}
      {scenes.length > 0 && (
        <div style={{ marginBottom: '32px' }}>
          <h3
            style={{
              fontSize: '14px',
              fontWeight: 500,
              color: 'rgba(255, 255, 255, 0.6)',
              marginBottom: '12px',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
            }}
          >
            Scenes ({scenes.length})
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {scenes.map((scene) => (
              <button
                key={scene.scene_id}
                onClick={() => onNavigateToScene?.(scene.scene_id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  padding: '12px 16px',
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  textAlign: 'left',
                  transition: 'background 0.15s',
                }}
              >
                <span style={{ fontSize: '18px' }}>📅</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      color: '#f3f4f6',
                      fontSize: '14px',
                      fontWeight: 500,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {scene.title}
                    {scene.is_recurring && (
                      <span style={{ marginLeft: '8px', opacity: 0.5 }}>🔄</span>
                    )}
                  </div>
                  <div
                    style={{
                      color: 'rgba(255, 255, 255, 0.4)',
                      fontSize: '12px',
                      marginTop: '2px',
                    }}
                  >
                    {formatTime(scene.scheduled_at)}
                    {scene.act_title && ` · ${scene.act_title}`}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Todos */}
      {todos.length > 0 && (
        <div>
          <h3
            style={{
              fontSize: '14px',
              fontWeight: 500,
              color: 'rgba(255, 255, 255, 0.6)',
              marginBottom: '12px',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
            }}
          >
            Unchecked Todos ({todos.length})
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {todos.slice(0, 10).map((todo) => (
              <button
                key={todo.id}
                onClick={() =>
                  onNavigateToBlock?.(todo.id, todo.act_id, todo.page_id)
                }
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  padding: '10px 16px',
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  textAlign: 'left',
                  transition: 'background 0.15s',
                }}
              >
                <input
                  type="checkbox"
                  checked={false}
                  readOnly
                  style={{
                    width: '16px',
                    height: '16px',
                    accentColor: '#22c55e',
                  }}
                />
                <span
                  style={{
                    color: '#e5e7eb',
                    fontSize: '13px',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {todo.rich_text.map((s) => s.content).join('') || 'Untitled todo'}
                </span>
              </button>
            ))}

            {todos.length > 10 && (
              <div
                style={{
                  color: 'rgba(255, 255, 255, 0.4)',
                  fontSize: '12px',
                  textAlign: 'center',
                  padding: '8px',
                }}
              >
                +{todos.length - 10} more todos
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default TodayView;
