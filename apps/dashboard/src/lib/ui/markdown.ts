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
  | { kind: 'list'; ordered: boolean; items: Span[][]; start?: number }
  | { kind: 'code'; text: string }
  | { kind: 'table'; align: Align[]; head: Span[][]; rows: Span[][][] }
  | { kind: 'rule' };

export type Align = 'left' | 'center' | 'right';

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
const NUMBER = /^\s*(\d+)[.)]\s+(.*)$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const FENCE = /^\s*```/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const DIVIDER_CELL = /^:?-+:?$/;

/** The cells of one table row. A pipe inside `code` or written as \| belongs to its cell. */
export function tableCells(line: string): string[] {
  const cells: string[] = [];
  let cell = '';
  let code = false;
  const text = line.trim();
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '\\' && text[i + 1] === '|') {
      cell += '|';
      i++;
    } else if (c === '|' && !code) {
      cells.push(cell.trim());
      cell = '';
    } else {
      if (c === '`') code = !code;
      cell += c;
    }
  }
  cells.push(cell.trim());
  if (text.startsWith('|')) cells.shift();
  if (text.endsWith('|') && !text.endsWith('\\|')) cells.pop();
  return cells;
}

/** How each column is aligned, when the line is the row of dashes under a table's heading; otherwise null. */
function tableDivider(line: string): Align[] | null {
  if (!line.includes('|') && !line.includes(':')) return null; // a bare "---" is a rule, not a one-column table
  const cells = tableCells(line);
  if (!cells.length || !cells.every((c) => DIVIDER_CELL.test(c))) return null;
  return cells.map((c) => (c.endsWith(':') ? (c.startsWith(':') ? 'center' : 'right') : 'left'));
}

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
    // A table: a row of cells, then a row of dashes with as many cells, then the rows until one has no pipe.
    const align = line.includes('|') && i + 1 < lines.length ? tableDivider(lines[i + 1]) : null;
    const head = align ? tableCells(line) : [];
    if (align && head.length === align.length) {
      flush();
      const rows: Span[][][] = [];
      for (i += 2; i < lines.length && lines[i].includes('|') && lines[i].trim(); i++) {
        const cells = tableCells(lines[i]);
        rows.push(head.map((_, column) => inline(cells[column] ?? '')));
      }
      i--;
      blocks.push({ kind: 'table', align, head: head.map(inline), rows });
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
    const bullet = BULLET.exec(line);
    const number = bullet ? null : NUMBER.exec(line);
    if (bullet || number) {
      flush();
      const text = inline(bullet ? bullet[1] : number![2]);
      const last = blocks.at(-1);
      if (last?.kind === 'list' && last.ordered === !bullet) last.items.push(text);
      else if (bullet) blocks.push({ kind: 'list', ordered: false, items: [text] });
      // A list that carries on after something else ("4." after a few bullets) keeps the number it starts at.
      else blocks.push({ kind: 'list', ordered: true, start: Number(number![1]), items: [text] });
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
