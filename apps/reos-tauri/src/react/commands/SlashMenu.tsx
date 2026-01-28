/**
 * SlashMenu - Floating menu component for slash commands.
 */

import { useState, useEffect, useCallback, forwardRef, useImperativeHandle } from 'react';
import type { Editor } from '@tiptap/react';
import { SlashMenuItem } from './SlashMenuItem';
import { filterCommands, type SlashCommand, type SlashCommandContext } from './slashCommands';

interface SlashMenuProps {
  editor: Editor;
  query: string;
  onClose: () => void;
  position: { top: number; left: number };
  /** Context for commands that require kernel access */
  context?: SlashCommandContext;
}

export interface SlashMenuHandle {
  onKeyDown: (event: KeyboardEvent) => boolean;
}

export const SlashMenu = forwardRef<SlashMenuHandle, SlashMenuProps>(
  function SlashMenu({ editor, query, onClose, position, context }, ref) {
    const [selectedIndex, setSelectedIndex] = useState(0);
    const commands = filterCommands(query);

    // Reset selection when query changes
    useEffect(() => {
      setSelectedIndex(0);
    }, [query]);

    const executeCommand = useCallback(
      async (command: SlashCommand) => {
        // Close menu first for better UX
        onClose();

        // Execute command with context if needed
        if (command.requiresContext && context) {
          await command.action(editor, context);
        } else {
          await command.action(editor);
        }
      },
      [editor, onClose, context],
    );

    // Expose keyboard handler to parent
    useImperativeHandle(
      ref,
      () => ({
        onKeyDown: (event: KeyboardEvent) => {
          if (event.key === 'ArrowDown') {
            event.preventDefault();
            setSelectedIndex((prev) => (prev + 1) % commands.length);
            return true;
          }

          if (event.key === 'ArrowUp') {
            event.preventDefault();
            setSelectedIndex((prev) => (prev - 1 + commands.length) % commands.length);
            return true;
          }

          if (event.key === 'Enter') {
            event.preventDefault();
            if (commands.length > 0) {
              executeCommand(commands[selectedIndex]);
            }
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
      [commands, selectedIndex, executeCommand, onClose],
    );

    if (commands.length === 0) {
      return (
        <div
          style={{
            position: 'absolute',
            top: position.top,
            left: position.left,
            background: '#1f1f23',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '8px',
            boxShadow: '0 4px 20px rgba(0, 0, 0, 0.4)',
            padding: '8px',
            minWidth: '220px',
            zIndex: 1000,
          }}
        >
          <div
            style={{
              color: 'rgba(255, 255, 255, 0.4)',
              fontSize: '12px',
              textAlign: 'center',
              padding: '8px',
            }}
          >
            No matching commands
          </div>
        </div>
      );
    }

    return (
      <div
        style={{
          position: 'absolute',
          top: position.top,
          left: position.left,
          background: '#1f1f23',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          borderRadius: '8px',
          boxShadow: '0 4px 20px rgba(0, 0, 0, 0.4)',
          padding: '4px',
          minWidth: '220px',
          maxWidth: '280px',
          maxHeight: '300px',
          overflowY: 'auto',
          zIndex: 1000,
        }}
      >
        {commands.map((command, index) => (
          <SlashMenuItem
            key={command.id}
            command={command}
            isSelected={index === selectedIndex}
            onClick={() => executeCommand(command)}
          />
        ))}
      </div>
    );
  },
);

export default SlashMenu;
