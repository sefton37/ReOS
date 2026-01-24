/**
 * WaitingOnView - Shows scenes in the awaiting_data stage.
 */

import { useState, useEffect } from 'react';

interface Scene {
  scene_id: string;
  title: string;
  act_id: string;
  act_title?: string;
  act_color?: string;
  stage: string;
  scheduled_at: string | null;
  is_recurring: boolean;
  notes?: string;
}

interface WaitingOnViewProps {
  kernelRequest: (method: string, params: Record<string, unknown>) => Promise<unknown>;
  onNavigateToScene?: (sceneId: string) => void;
  onUpdateScene?: (sceneId: string, stage: string) => void;
}

export function WaitingOnView({
  kernelRequest,
  onNavigateToScene,
  onUpdateScene,
}: WaitingOnViewProps) {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      setLoading(true);

      try {
        const result = (await kernelRequest('play/scenes/list_all', {})) as {
          scenes: Scene[];
        };

        // Filter to only awaiting_data scenes
        const waitingScenes = (result.scenes ?? []).filter(
          (scene) => scene.stage === 'awaiting_data',
        );
        setScenes(waitingScenes);
      } catch (error) {
        console.error('Failed to load waiting scenes:', error);
        setScenes([]);
      } finally {
        setLoading(false);
      }
    }

    void loadData();
  }, [kernelRequest]);

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return 'Unscheduled';
    try {
      const date = new Date(dateStr);
      return date.toLocaleDateString('en-US', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return 'Unscheduled';
    }
  };

  const handleMarkReady = async (sceneId: string) => {
    if (onUpdateScene) {
      onUpdateScene(sceneId, 'in_progress');
      // Optimistically remove from list
      setScenes((prev) => prev.filter((s) => s.scene_id !== sceneId));
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
      <h2
        style={{
          fontSize: '20px',
          fontWeight: 600,
          color: '#f3f4f6',
          marginBottom: '24px',
        }}
      >
        Waiting On ({scenes.length})
      </h2>

      {scenes.length === 0 && (
        <div
          style={{
            padding: '32px',
            textAlign: 'center',
            color: 'rgba(255, 255, 255, 0.4)',
            background: 'rgba(255, 255, 255, 0.03)',
            borderRadius: '12px',
          }}
        >
          <div style={{ fontSize: '32px', marginBottom: '8px' }}>⏳</div>
          <div>No scenes awaiting data</div>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {scenes.map((scene) => (
          <div
            key={scene.scene_id}
            style={{
              padding: '16px',
              background: 'rgba(139, 92, 246, 0.05)',
              border: '1px solid rgba(139, 92, 246, 0.2)',
              borderRadius: '12px',
            }}
          >
            {/* Header */}
            <div
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: '12px',
                marginBottom: scene.notes ? '12px' : '0',
              }}
            >
              <span style={{ fontSize: '20px' }}>⏳</span>

              <div style={{ flex: 1, minWidth: 0 }}>
                <button
                  onClick={() => onNavigateToScene?.(scene.scene_id)}
                  style={{
                    display: 'block',
                    border: 'none',
                    background: 'transparent',
                    padding: 0,
                    cursor: 'pointer',
                    textAlign: 'left',
                    width: '100%',
                  }}
                >
                  <div
                    style={{
                      color: '#f3f4f6',
                      fontSize: '15px',
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
                </button>

                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    marginTop: '4px',
                    color: 'rgba(255, 255, 255, 0.4)',
                    fontSize: '12px',
                  }}
                >
                  <span>{formatDate(scene.scheduled_at)}</span>
                  {scene.act_title && (
                    <>
                      <span>·</span>
                      <span
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px',
                        }}
                      >
                        <span
                          style={{
                            width: '6px',
                            height: '6px',
                            borderRadius: '50%',
                            background: scene.act_color || '#8b5cf6',
                          }}
                        />
                        {scene.act_title}
                      </span>
                    </>
                  )}
                </div>
              </div>

              {/* Mark ready button */}
              <button
                onClick={() => handleMarkReady(scene.scene_id)}
                title="Mark as ready"
                style={{
                  padding: '6px 12px',
                  background: 'rgba(34, 197, 94, 0.1)',
                  border: '1px solid rgba(34, 197, 94, 0.3)',
                  borderRadius: '6px',
                  color: '#22c55e',
                  fontSize: '12px',
                  fontWeight: 500,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                Ready
              </button>
            </div>

            {/* Notes */}
            {scene.notes && (
              <div
                style={{
                  padding: '12px',
                  background: 'rgba(0, 0, 0, 0.2)',
                  borderRadius: '8px',
                  color: 'rgba(255, 255, 255, 0.6)',
                  fontSize: '13px',
                  lineHeight: 1.5,
                }}
              >
                {scene.notes}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default WaitingOnView;
