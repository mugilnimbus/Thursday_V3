/* A small markdown reader for replies from the agents. It returns plain data (blocks and spans);
   Markdown.svelte turns that into elements. Model output is untrusted, so nothing here or there ever
   becomes raw HTML: unknown syntax simply stays as text. Pure, so it is unit tested. */

export type Span =
  | { kind: 'text'; text: string }
  | { kind: 'bold'; spans: Span[] }
  | { kind: 'italic'; spans: Span[] }
  | { kind: 'code'; text: string }
  | { kind: 'link'; text: string; href: string };

export type Block =
  | { kind: 'heading'; level: number; spans: Span[] }
  | { kind: 'paragraph'; spans: Span[] }
  | { kind: 'list'; ordered: boolean; items: Span[][] }
  | { kind: 'code'; text: string }
  | { kind: 'rule' };

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+?\*\*)|(__[^_\n]+?__)|(\*[^*\s][^*\n]*?\*)|(\[[^\]\n]+\]\([^)\s]+\))/;

export function inline(text: string): Span[] {
  const spans: Span[] = [];
  let rest = text;
  while (rest) {
    const m = INLINE.exec(rest);
    if (!m) {
      spans.push({ kind: 'text', text: rest });
      break;
    }
    if (m.index) spans.push({ kind: 'text', text: rest.slice(0, m.index) });
    const hit = m[0];
    if (m[1]) spans.push({ kind: 'code', text: hit.slice(1, -1) });
    else if (m[2] || m[3]) spans.push({ kind: 'bold', spans: inline(hit.slice(2, -2)) });
    else if (m[4]) spans.push({ kind: 'italic', spans: inline(hit.slice(1, -1)) });
    else {
      const close = hit.indexOf('](');
      const label = hit.slice(1, close);
      const href = hit.slice(close + 2, -1);
      // Only web links become links; anything else (javascript:, file:, …) stays as text.
      spans.push(/^https?:\/\//i.test(href) ? { kind: 'link', text: label, href } : { kind: 'text', text: hit });
    }
    rest = rest.slice(m.index + hit.length);
  }
  return spans;
}

const BULLET = /^\s*[-*+•]\s+(.*)$/;
const NUMBER = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const FENCE = /^\s*```/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;

export function parse(markdown: string): Block[] {
  const blocks: Block[] = [];
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n');
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: 'paragraph', spans: inline(paragraph.join('\n')) });
    paragraph = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (FENCE.test(line)) {
      flush();
      const code: string[] = [];
      for (i++; i < lines.length && !FENCE.test(lines[i]); i++) code.push(lines[i]);
      blocks.push({ kind: 'code', text: code.join('\n') });
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      blocks.push({ kind: 'heading', level: heading[1].length, spans: inline(heading[2]) });
      continue;
    }
    if (RULE.test(line)) {
      flush();
      blocks.push({ kind: 'rule' });
      continue;
    }
    const item = BULLET.exec(line) ?? NUMBER.exec(line);
    if (item) {
      flush();
      const ordered = !BULLET.test(line);
      const last = blocks.at(-1);
      if (last?.kind === 'list' && last.ordered === ordered) last.items.push(inline(item[1]));
      else blocks.push({ kind: 'list', ordered, items: [inline(item[1])] });
      continue;
    }
    // An indented line right after a list item continues that item.
    const last = blocks.at(-1);
    if (last?.kind === 'list' && /^\s{2,}\S/.test(line) && !paragraph.length) {
      last.items[last.items.length - 1].push(...inline(' ' + line.trim()));
      continue;
    }
    paragraph.push(line);
  }
  flush();
  return blocks;
}

/** True when the text has no markdown worth rendering, so it can be shown as it is. */
export function isPlain(markdown: string): boolean {
  const blocks = parse(markdown);
  return blocks.every((b) => b.kind === 'paragraph' && b.spans.every((s) => s.kind === 'text'));
}
