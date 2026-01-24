/**
 * Tests for RichTextContent component.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RichTextContent } from '../blocks/RichTextContent';
import type { RichTextSpan } from '../types';

// Helper to create a span with defaults
function createSpan(overrides: Partial<RichTextSpan> = {}): RichTextSpan {
  return {
    id: 'span-1',
    block_id: 'block-1',
    position: 0,
    content: 'Test content',
    bold: false,
    italic: false,
    strikethrough: false,
    code: false,
    underline: false,
    color: null,
    background_color: null,
    link_url: null,
    ...overrides,
  };
}

describe('RichTextContent', () => {
  it('renders null for empty spans array', () => {
    const { container } = render(<RichTextContent spans={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders plain text content', () => {
    const spans = [createSpan({ content: 'Hello world' })];
    render(<RichTextContent spans={spans} />);
    expect(screen.getByText('Hello world')).toBeInTheDocument();
  });

  it('renders multiple spans', () => {
    const spans = [
      createSpan({ id: '1', content: 'First ', position: 0 }),
      createSpan({ id: '2', content: 'Second', position: 1 }),
    ];
    const { container } = render(<RichTextContent spans={spans} />);
    // Plain text spans render as adjacent text nodes without wrapper elements
    expect(container.textContent).toBe('First Second');
  });

  describe('formatting', () => {
    it('renders bold text with <strong> tag', () => {
      const spans = [createSpan({ content: 'Bold text', bold: true })];
      render(<RichTextContent spans={spans} />);
      const element = screen.getByText('Bold text');
      expect(element.tagName).toBe('STRONG');
    });

    it('renders italic text with <em> tag', () => {
      const spans = [createSpan({ content: 'Italic text', italic: true })];
      render(<RichTextContent spans={spans} />);
      const element = screen.getByText('Italic text');
      expect(element.tagName).toBe('EM');
    });

    it('renders strikethrough text with <s> tag', () => {
      const spans = [createSpan({ content: 'Struck text', strikethrough: true })];
      render(<RichTextContent spans={spans} />);
      const element = screen.getByText('Struck text');
      expect(element.tagName).toBe('S');
    });

    it('renders code text with <code> tag', () => {
      const spans = [createSpan({ content: 'inline_code', code: true })];
      render(<RichTextContent spans={spans} />);
      const element = screen.getByText('inline_code');
      expect(element.tagName).toBe('CODE');
    });

    it('renders underlined text with <u> tag', () => {
      const spans = [createSpan({ content: 'Underlined', underline: true })];
      render(<RichTextContent spans={spans} />);
      const element = screen.getByText('Underlined');
      expect(element.tagName).toBe('U');
    });

    it('renders combined formatting correctly', () => {
      const spans = [createSpan({ content: 'Bold and italic', bold: true, italic: true })];
      render(<RichTextContent spans={spans} />);

      // Find the text - bold is applied first, then italic wraps it
      // So structure is <em><strong>text</strong></em>
      const boldElement = screen.getByText('Bold and italic');
      expect(boldElement.tagName).toBe('STRONG');

      // Parent should be em (italic wraps bold)
      expect(boldElement.parentElement?.tagName).toBe('EM');
    });
  });

  describe('links', () => {
    it('renders link with href', () => {
      const spans = [
        createSpan({
          content: 'Click here',
          link_url: 'https://example.com',
        }),
      ];
      render(<RichTextContent spans={spans} />);

      const link = screen.getByRole('link', { name: 'Click here' });
      expect(link).toHaveAttribute('href', 'https://example.com');
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    });

    it('renders formatted link text', () => {
      const spans = [
        createSpan({
          content: 'Bold link',
          bold: true,
          link_url: 'https://example.com',
        }),
      ];
      render(<RichTextContent spans={spans} />);

      const link = screen.getByRole('link', { name: 'Bold link' });
      expect(link).toBeInTheDocument();

      // The <strong> should be inside the <a>
      expect(link.querySelector('strong')).toBeInTheDocument();
    });
  });

  describe('colors', () => {
    it('applies text color', () => {
      const spans = [createSpan({ content: 'Colored', color: '#ff0000' })];
      render(<RichTextContent spans={spans} />);

      const element = screen.getByText('Colored');
      expect(element).toHaveStyle({ color: '#ff0000' });
    });

    it('applies background color', () => {
      const spans = [createSpan({ content: 'Highlighted', background_color: '#ffff00' })];
      render(<RichTextContent spans={spans} />);

      const element = screen.getByText('Highlighted');
      expect(element).toHaveStyle({ backgroundColor: '#ffff00' });
    });

    it('applies both text and background color', () => {
      const spans = [
        createSpan({
          content: 'Both colors',
          color: '#ffffff',
          background_color: '#333333',
        }),
      ];
      render(<RichTextContent spans={spans} />);

      const element = screen.getByText('Both colors');
      expect(element).toHaveStyle({
        color: '#ffffff',
        backgroundColor: '#333333',
      });
    });
  });
});
