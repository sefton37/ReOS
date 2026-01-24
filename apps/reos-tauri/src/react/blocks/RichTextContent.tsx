/**
 * RichTextContent - Renders an array of rich text spans with formatting.
 */

import type { RichTextSpan } from '../types';

interface RichTextContentProps {
  spans: RichTextSpan[];
}

export function RichTextContent({ spans }: RichTextContentProps) {
  if (!spans || spans.length === 0) {
    return null;
  }

  return (
    <>
      {spans.map((span) => (
        <RichTextSpanComponent key={span.id} span={span} />
      ))}
    </>
  );
}

interface RichTextSpanComponentProps {
  span: RichTextSpan;
}

function RichTextSpanComponent({ span }: RichTextSpanComponentProps) {
  let content: React.ReactNode = span.content;

  // Apply formatting in order: bold, italic, strikethrough, code, underline
  if (span.bold) {
    content = <strong style={{ fontWeight: 600, color: '#f9fafb' }}>{content}</strong>;
  }

  if (span.italic) {
    content = <em>{content}</em>;
  }

  if (span.strikethrough) {
    content = <s style={{ opacity: 0.7 }}>{content}</s>;
  }

  if (span.code) {
    content = (
      <code
        style={{
          background: 'rgba(0, 0, 0, 0.3)',
          padding: '0.2em 0.4em',
          borderRadius: '4px',
          fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          fontSize: '0.9em',
        }}
      >
        {content}
      </code>
    );
  }

  if (span.underline) {
    content = <u>{content}</u>;
  }

  // Apply link
  if (span.link_url) {
    content = (
      <a
        href={span.link_url}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          color: '#60a5fa',
          textDecoration: 'underline',
          cursor: 'pointer',
        }}
      >
        {content}
      </a>
    );
  }

  // Apply colors
  const style: React.CSSProperties = {};
  if (span.color) {
    style.color = span.color;
  }
  if (span.background_color) {
    style.backgroundColor = span.background_color;
    style.padding = '0.1em 0.2em';
    style.borderRadius = '2px';
  }

  if (Object.keys(style).length > 0) {
    return <span style={style}>{content}</span>;
  }

  return <>{content}</>;
}

export default RichTextContent;
