import DOMPurify from 'dompurify';
import { marked } from 'marked';

const ALLOWED_TAGS = [
  'a', 'blockquote', 'br', 'code', 'del', 'em', 'h1', 'h2', 'h3', 'h4', 'hr',
  'li', 'ol', 'p', 'pre', 'strong', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'ul',
];

export function renderMarkdownInto(target: HTMLElement, source: string): void {
  if (!source.trim()) {
    target.replaceChildren();
    return;
  }

  const parsed = marked.parse(source, { async: false, breaks: true, gfm: true });
  const sanitized = DOMPurify.sanitize(String(parsed), {
    ALLOWED_ATTR: ['href', 'title'],
    ALLOWED_TAGS,
  });
  const template = document.createElement('template');
  template.innerHTML = String(sanitized);
  template.content.querySelectorAll('a').forEach((anchor) => secureExternalLink(anchor));
  target.replaceChildren(template.content.cloneNode(true));
}

function secureExternalLink(anchor: HTMLAnchorElement): void {
  const href = anchor.getAttribute('href');
  if (!href) return;
  try {
    const url = new URL(href, window.location.href);
    if (!['http:', 'https:'].includes(url.protocol)) {
      anchor.removeAttribute('href');
      return;
    }
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
  } catch {
    anchor.removeAttribute('href');
  }
}
