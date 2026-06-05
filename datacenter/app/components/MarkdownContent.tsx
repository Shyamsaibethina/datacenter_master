'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';

function buildComponents(invert: boolean): Components {
  const text = invert ? 'text-white' : 'text-gray-900';
  const muted = invert ? 'text-blue-100' : 'text-gray-700';
  const codeBg = invert ? 'bg-white/20' : 'bg-gray-200';
  const border = invert ? 'border-white/30' : 'border-gray-300';
  const thBg = invert ? 'bg-white/15' : 'bg-gray-200';

  return {
    h1: ({ children }) => (
      <h1 className={`text-base font-bold mt-3 mb-1.5 first:mt-0 ${text}`}>{children}</h1>
    ),
    h2: ({ children }) => (
      <h2 className={`text-sm font-bold mt-3 mb-1 first:mt-0 ${text}`}>{children}</h2>
    ),
    h3: ({ children }) => (
      <h3 className={`text-sm font-semibold mt-2 mb-1 first:mt-0 ${text}`}>{children}</h3>
    ),
    p: ({ children }) => (
      <p className={`text-sm mb-2 last:mb-0 leading-relaxed ${muted}`}>{children}</p>
    ),
    ul: ({ children }) => (
      <ul className={`text-sm list-disc pl-4 mb-2 space-y-1 ${muted}`}>{children}</ul>
    ),
    ol: ({ children }) => (
      <ol className={`text-sm list-decimal pl-4 mb-2 space-y-1 ${muted}`}>{children}</ol>
    ),
    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
    strong: ({ children }) => <strong className={`font-semibold ${text}`}>{children}</strong>,
    em: ({ children }) => <em className="italic">{children}</em>,
    code: ({ className, children }) => {
      const isBlock = className?.includes('language-');
      if (isBlock) {
        return <code className={`${className} font-mono text-xs`}>{children}</code>;
      }
      return (
        <code className={`${codeBg} rounded px-1 py-0.5 text-xs font-mono ${text}`}>{children}</code>
      );
    },
    pre: ({ children }) => (
      <pre className={`${codeBg} rounded p-2 overflow-x-auto text-xs mb-2 font-mono`}>{children}</pre>
    ),
    table: ({ children }) => (
      <div className="overflow-x-auto mb-2 -mx-1">
        <table className={`text-xs border-collapse w-full ${text}`}>{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead>{children}</thead>,
    tbody: ({ children }) => <tbody>{children}</tbody>,
    tr: ({ children }) => <tr className="border-b border-gray-200">{children}</tr>,
    th: ({ children }) => (
      <th className={`border ${border} px-2 py-1 ${thBg} font-semibold text-left`}>{children}</th>
    ),
    td: ({ children }) => <td className={`border ${border} px-2 py-1 ${muted}`}>{children}</td>,
    a: ({ href, children }) => (
      <a
        href={href}
        className={invert ? 'text-blue-200 underline' : 'text-blue-600 underline'}
        target="_blank"
        rel="noopener noreferrer"
      >
        {children}
      </a>
    ),
    blockquote: ({ children }) => (
      <blockquote className={`border-l-2 ${border} pl-3 italic mb-2 ${muted}`}>{children}</blockquote>
    ),
    hr: () => <hr className={`my-3 ${border}`} />,
  };
}

interface MarkdownContentProps {
  content: string;
  /** Light text on dark bubbles (user messages) */
  invert?: boolean;
}

export default function MarkdownContent({ content, invert = false }: MarkdownContentProps) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildComponents(invert)}>
      {content}
    </ReactMarkdown>
  );
}
