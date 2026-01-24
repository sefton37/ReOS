/**
 * FormattingToolbar - Floating toolbar that appears on text selection.
 * Provides formatting controls for bold, italic, code, strikethrough, and links.
 */

import { useState, useCallback, useEffect } from 'react';
import type { Editor } from '@tiptap/react';
import { BubbleMenu } from '@tiptap/react';

interface FormattingToolbarProps {
  editor: Editor;
}

interface ToolbarButtonProps {
  isActive: boolean;
  onClick: () => void;
  title: string;
  children: React.ReactNode;
}

function ToolbarButton({ isActive, onClick, title, children }: ToolbarButtonProps) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: '28px',
        height: '28px',
        border: 'none',
        borderRadius: '4px',
        background: isActive ? 'rgba(34, 197, 94, 0.2)' : 'transparent',
        color: isActive ? '#22c55e' : '#e5e7eb',
        cursor: 'pointer',
        fontSize: '13px',
        fontWeight: isActive ? 600 : 400,
        transition: 'all 0.1s',
      }}
      onMouseEnter={(e) => {
        if (!isActive) {
          e.currentTarget.style.background = 'rgba(255, 255, 255, 0.1)';
        }
      }}
      onMouseLeave={(e) => {
        if (!isActive) {
          e.currentTarget.style.background = 'transparent';
        }
      }}
    >
      {children}
    </button>
  );
}

function Divider() {
  return (
    <div
      style={{
        width: '1px',
        height: '20px',
        background: 'rgba(255, 255, 255, 0.1)',
        margin: '0 4px',
      }}
    />
  );
}

export function FormattingToolbar({ editor }: FormattingToolbarProps) {
  const [showLinkInput, setShowLinkInput] = useState(false);
  const [linkUrl, setLinkUrl] = useState('');

  // Reset link input when selection changes
  useEffect(() => {
    const existingLink = editor.getAttributes('link').href;
    setLinkUrl(existingLink || '');
    setShowLinkInput(false);
  }, [editor.state.selection]);

  const toggleBold = useCallback(() => {
    editor.chain().focus().toggleBold().run();
  }, [editor]);

  const toggleItalic = useCallback(() => {
    editor.chain().focus().toggleItalic().run();
  }, [editor]);

  const toggleStrike = useCallback(() => {
    editor.chain().focus().toggleStrike().run();
  }, [editor]);

  const toggleCode = useCallback(() => {
    editor.chain().focus().toggleCode().run();
  }, [editor]);

  const handleLinkClick = useCallback(() => {
    if (editor.isActive('link')) {
      // Remove existing link
      editor.chain().focus().unsetLink().run();
    } else {
      // Show link input
      setShowLinkInput(true);
    }
  }, [editor]);

  const submitLink = useCallback(() => {
    if (linkUrl.trim()) {
      let url = linkUrl.trim();
      // Add protocol if missing
      if (!/^https?:\/\//i.test(url)) {
        url = 'https://' + url;
      }
      editor.chain().focus().setLink({ href: url }).run();
    }
    setShowLinkInput(false);
    setLinkUrl('');
  }, [editor, linkUrl]);

  const cancelLink = useCallback(() => {
    setShowLinkInput(false);
    setLinkUrl('');
  }, []);

  return (
    <BubbleMenu
      editor={editor}
      tippyOptions={{
        duration: 100,
        placement: 'top',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '2px',
          padding: '4px',
          background: '#1f1f23',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          borderRadius: '8px',
          boxShadow: '0 4px 20px rgba(0, 0, 0, 0.4)',
        }}
      >
        {showLinkInput ? (
          // Link input mode
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <input
              type="text"
              value={linkUrl}
              onChange={(e) => setLinkUrl(e.target.value)}
              placeholder="Enter URL..."
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  submitLink();
                } else if (e.key === 'Escape') {
                  e.preventDefault();
                  cancelLink();
                }
              }}
              style={{
                width: '180px',
                padding: '4px 8px',
                border: '1px solid rgba(255, 255, 255, 0.2)',
                borderRadius: '4px',
                background: 'rgba(0, 0, 0, 0.3)',
                color: '#e5e7eb',
                fontSize: '12px',
                outline: 'none',
              }}
            />
            <ToolbarButton isActive={false} onClick={submitLink} title="Add link">
              ✓
            </ToolbarButton>
            <ToolbarButton isActive={false} onClick={cancelLink} title="Cancel">
              ✕
            </ToolbarButton>
          </div>
        ) : (
          // Formatting buttons mode
          <>
            <ToolbarButton
              isActive={editor.isActive('bold')}
              onClick={toggleBold}
              title="Bold (Cmd+B)"
            >
              <strong>B</strong>
            </ToolbarButton>

            <ToolbarButton
              isActive={editor.isActive('italic')}
              onClick={toggleItalic}
              title="Italic (Cmd+I)"
            >
              <em>I</em>
            </ToolbarButton>

            <ToolbarButton
              isActive={editor.isActive('strike')}
              onClick={toggleStrike}
              title="Strikethrough"
            >
              <s>S</s>
            </ToolbarButton>

            <ToolbarButton
              isActive={editor.isActive('code')}
              onClick={toggleCode}
              title="Code"
            >
              {'<>'}
            </ToolbarButton>

            <Divider />

            <ToolbarButton
              isActive={editor.isActive('link')}
              onClick={handleLinkClick}
              title={editor.isActive('link') ? 'Remove link' : 'Add link (Cmd+K)'}
            >
              🔗
            </ToolbarButton>
          </>
        )}
      </div>
    </BubbleMenu>
  );
}

export default FormattingToolbar;
