import { describe, expect, it } from 'vitest';
import { inline, isPlain, parse, tableCells } from './markdown';

describe('markdown', () => {
  it('reads headings, lists and paragraphs like an agent reply', () => {
    const blocks = parse('Done. Summary:\n\n### 1. `README.md` (High level)\n*   **Core**: roles\n*   **Loop**: the cycle\n\nAll good.');
    expect(blocks.map((b) => b.kind)).toEqual(['paragraph', 'heading', 'list', 'paragraph']);
    expect(blocks[1]).toMatchObject({ level: 3, spans: [{ kind: 'text', text: '1. ' }, { kind: 'code', text: 'README.md' }, { kind: 'text', text: ' (High level)' }] });
    expect(blocks[2]).toMatchObject({ ordered: false, items: [[{ kind: 'bold' }, { kind: 'text', text: ': roles' }], [{ kind: 'bold' }, { kind: 'text', text: ': the cycle' }]] });
  });

  it('keeps code fences verbatim and separate numbered lists', () => {
    const blocks = parse('1. one\n2. two\n\n```py\nx = **not bold**\n```');
    expect(blocks[0]).toMatchObject({ kind: 'list', ordered: true, start: 1 });
    const carriedOn = parse('2. second\n3. third\n- a note\n4. fourth\n5. fifth');
    expect(carriedOn.map((b) => (b.kind === 'list' ? (b.start ?? 'bullets') : b.kind)), 'numbering carries on after the bullets').toEqual([2, 'bullets', 4]);
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

  it('reads a table: heading row, a row of dashes, then the rows', () => {
    const blocks = parse('Files:\n\n| File | Purpose | Lines |\n|:--|:-:|--:|\n| `train.py` | **Training** loop | 120 |\n| watch_model.py | Monitoring |\nDone.');
    expect(blocks.map((b) => b.kind)).toEqual(['paragraph', 'table', 'paragraph']);
    expect(blocks[1]).toEqual({
      kind: 'table',
      align: ['left', 'center', 'right'],
      head: [[{ kind: 'text', text: 'File' }], [{ kind: 'text', text: 'Purpose' }], [{ kind: 'text', text: 'Lines' }]],
      rows: [
        [[{ kind: 'code', text: 'train.py' }], [{ kind: 'bold', spans: [{ kind: 'text', text: 'Training' }] }, { kind: 'text', text: ' loop' }], [{ kind: 'text', text: '120' }]],
        [[{ kind: 'text', text: 'watch_model.py' }], [{ kind: 'text', text: 'Monitoring' }], []],
      ],
    });
  });

  it('keeps a pipe that is inside code or escaped in its cell, and reads a table without outer pipes', () => {
    expect(tableCells('| `a | b` | x \\| y |')).toEqual(['`a | b`', 'x | y']);
    expect(parse('Name | Value\n--- | ---\none | 1')[0]).toMatchObject({ kind: 'table', align: ['left', 'left'], rows: [[[{ kind: 'text', text: 'one' }], [{ kind: 'text', text: '1' }]]] });
  });

  it('does not take other lines with pipes or dashes for a table', () => {
    expect(parse('use a | b to pipe\n---').map((b) => b.kind)).toEqual(['paragraph', 'rule']);
    expect(parse('| only a heading row |').map((b) => b.kind)).toEqual(['paragraph']);
    expect(parse('| a | b |\n|---|').map((b) => b.kind), 'the dashes must have as many cells as the heading').toEqual(['paragraph']);
    expect(parse('| a | b |\n|---|---|').map((b) => b.kind), 'a table that is still being written has no rows yet').toEqual(['table']);
  });

  it('survives text that was cut off mid-markup', () => {
    expect(parse('for both **Off-Policy** (')[0]).toMatchObject({ kind: 'paragraph' });
    expect(parse('an **unfinished bold')[0]).toEqual({ kind: 'paragraph', spans: [{ kind: 'text', text: 'an **unfinished bold' }] });
  });
});
