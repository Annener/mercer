import { useEffect, useMemo, useRef } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import javascript from 'highlight.js/lib/languages/javascript';
import bash from 'highlight.js/lib/languages/bash';
import json from 'highlight.js/lib/languages/json';
import yaml from 'highlight.js/lib/languages/yaml';
import sql from 'highlight.js/lib/languages/sql';
import { clsx } from '@/components/ui/clsx';

let configured = false;

function configureMarked(): void {
  if (configured) return;
  configured = true;

  hljs.registerLanguage('python', python);
  hljs.registerLanguage('javascript', javascript);
  hljs.registerLanguage('bash', bash);
  hljs.registerLanguage('json', json);
  hljs.registerLanguage('yaml', yaml);
  hljs.registerLanguage('sql', sql);

  marked.setOptions({
    breaks: true,
    gfm: true,
  });

  const renderer = new marked.Renderer();
  renderer.code = function (codeOrToken, langMaybe) {
    let text: string;
    let lang: string | undefined;
    if (typeof codeOrToken === 'object' && codeOrToken !== null) {
      text = (codeOrToken as { text: string }).text;
      lang = (codeOrToken as { lang?: string }).lang;
    } else {
      text = codeOrToken;
      lang = langMaybe as string | undefined;
    }
    const validLang = lang && hljs.getLanguage(lang) ? lang : null;
    let highlighted: string;
    try {
      highlighted = validLang
        ? hljs.highlight(text, { language: validLang }).value
        : hljs.highlightAuto(text).value;
    } catch {
      highlighted = escapeHtml(text);
    }
    const langLabel = validLang
      ? `<span class="code-lang">${validLang}</span>`
      : '';
    return `<pre class="code-block">${langLabel}<code class="hljs">${highlighted}</code></pre>`;
  };
  marked.use({ renderer });
}

const CALLOUT_LABELS: Record<string, string> = {
  NOTE: 'Заметка',
  TIP: 'Совет',
  IMPORTANT: 'Важно',
  WARNING: 'Предупреждение',
  CAUTION: 'Осторожно',
};

function preprocessMarkdown(text: string): string {
  if (!text) return text;
  return text.replace(
    /^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*/gm,
    (_, type) => `> **${CALLOUT_LABELS[type] ?? type}:** `,
  );
}

function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

interface MarkdownProps {
  content: string;
  className?: string;
  variant?: 'default' | 'inverse';
}

export function Markdown({ content, className, variant = 'default' }: MarkdownProps) {
  useEffect(() => {
    configureMarked();
  }, []);

  const html = useMemo(() => {
    if (!content) return '';
    const rawHtml = marked.parse(preprocessMarkdown(content), { async: false }) as string;
    return DOMPurify.sanitize(rawHtml, {
      ADD_ATTR: ['target'],
      FORBID_TAGS: ['script', 'style', 'iframe'],
    });
  }, [content]);

  const ref = useRef<HTMLDivElement>(null);

  return (
    <div
      ref={ref}
      className={clsx('markdown', variant === 'inverse' && 'markdown-inverse', className)}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}