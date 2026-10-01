import { describe, expect, it } from 'vitest';
import { inline, isPlain, parse } from './markdown';

describe('markdown', () => {
  it('reads headings, lists and paragraphs like an agent reply', () => {
    const blocks = parse('Done. Summary:\n\n### 1. `README.md` (High level)\n*   **Core**: roles\n*   **Loop**: the cycle\n\nAll good.');
    expect(blocks.map((b) => b.kind)).toEqual(['paragraph', 'heading', 'list', 'paragraph']);
    expect(blocks[1]).toMatchObject({ level: 3, spans: [{ kind: 'text', text: '1. ' }, { kind: 'code', text: 'README.md' }, { kind: 'text', text: ' (High level)' }] });
    expect(blocks[2]).toMatchObject({ ordered: false, items: [[{ kind: 'bold' }, { kind: 'text', text: ': roles' }], [{ kind: 'bold' }, { kind: 'text', text: ': the cycle' }]] });
  });

  it('keeps code fences verbatim and separate numbered lists', () => {
    const blocks = parse('1. one\n2. two\n\n```py\nx = **not bold**\n```');
    expect(blocks[0]).toMatchObject({ kind: 'list', ordered: true });
    expect(blocks[1]).toEqual({ kind: 'code', text: 'x = **not bold**' });
  });

  it('only turns web addresses into links', () => {
    expect(inline('[docs](https://example.com/a) and [bad](javascript:alert(1))')).toEqual([
      { kind: 'link', text: 'docs', href: 'https://example.com/a' },
      { kind: 'text', text: ' and ' },
      { kind: 'text', text: '[bad](javascript:alert(1)' },
      { kind: 'text', text: ')' },
    ]);
  });

  it('leaves html and stray symbols as plain text', () => {
    expect(parse('<img src=x onerror=alert(1)> 2 * 3 * 4')).toEqual([{ kind: 'paragraph', spans: [{ kind: 'text', text: '<img src=x onerror=alert(1)> 2 * 3 * 4' }] }]);
    expect(isPlain('Hi there! How can I help?')).toBe(true);
    expect(isPlain('Use `ls` here')).toBe(false);
  });

  it('survives text that was cut off mid-markup', () => {
    expect(parse('for both **Off-Policy** (')[0]).toMatchObject({ kind: 'paragraph' });
    expect(parse('an **unfinished bold')[0]).toEqual({ kind: 'paragraph', spans: [{ kind: 'text', text: 'an **unfinished bold' }] });
  });
});
