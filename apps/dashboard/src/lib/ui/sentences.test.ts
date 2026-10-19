import { describe, expect, it } from 'vitest';
import { SentenceFeed, sayable, sentences } from './sentences';

describe('reading a reply aloud in pieces', () => {
  it('cuts a reply at the ends of sentences', () => {
    expect(sentences('The file tells Python how the project is built. It lists what the project needs! Is that clear enough?')).toEqual([
      'The file tells Python how the project is built.',
      'It lists what the project needs!',
      'Is that clear enough?',
    ]);
  });

  it('joins a short piece to the next, so one word is not a clip of its own', () => {
    expect(sentences('Okay. I started the task and will tell you when it is done.')).toEqual(['Okay. I started the task and will tell you when it is done.']);
    expect(sentences('Done.')).toEqual(['Done.']);
  });

  it('does not end a piece at a list number, an initial, a decimal or an abbreviation', () => {
    expect(sentences('Yes. There are 3.5 thousand files in the folder, e.g. the logs and the checkpoints. That is a lot of files.')).toEqual([
      'Yes. There are 3.5 thousand files in the folder,',
      'e.g. the logs and the checkpoints.',
      'That is a lot of files.',
    ]);
    expect(sentences('1. Open the settings page first\n2. Choose the models folder next')).toEqual(['1. Open the settings page first', '2. Choose the models folder next']);
  });

  it('takes each line of a list as a piece and skips what cannot be said', () => {
    expect(sentences('Here is what I found in it:\n- the training script for the model\n---\n- the saved checkpoints of the runs')).toEqual([
      'Here is what I found in it:',
      '- the training script for the model',
      '- the saved checkpoints of the runs',
    ]);
    expect([sayable('```'), sayable('--- ***'), sayable('ok')]).toEqual([false, false, true]);
  });

  it('gives out pieces while the reply is still being written, and the rest at the end', () => {
    const feed = new SentenceFeed();
    expect(feed.push('The task is running now')).toEqual([]);
    expect(feed.push('. I will')).toEqual(['The task is running now.']);
    expect(feed.push(' tell you when it is done.')).toEqual([]), 'the reply may go on after this full stop';
    expect(feed.flush()).toEqual(['I will tell you when it is done.']);
    expect(feed.flush()).toEqual([]);
  });

  it('gives the same pieces however the text arrives', () => {
    const text = 'First I listed the folder to see what is there. Then I read the two files that looked relevant, which took a moment. Nothing was changed.';
    const whole = sentences(text);
    for (const size of [1, 3, 7, 40]) {
      const feed = new SentenceFeed();
      const pieces: string[] = [];
      for (let i = 0; i < text.length; i += size) pieces.push(...feed.push(text.slice(i, i + size)));
      expect([...pieces, ...feed.flush()]).toEqual(whole);
    }
    expect(whole).toHaveLength(3);
  });

  it('ends the first piece of a reply at a comma, so the voice starts sooner, and only the first', () => {
    expect(sentences('I listed the folder, read the two files that looked relevant, and found the script. Nothing was changed, as you asked.')).toEqual([
      'I listed the folder,',
      'read the two files that looked relevant, and found the script.',
      'Nothing was changed, as you asked.',
    ]);
    const feed = new SentenceFeed();
    expect(feed.push('The task is running now, and')).toEqual(['The task is running now,']), 'given out as soon as the comma is passed';
    expect(feed.push(' it will take a while, I think. ')).toEqual([]);
    expect(feed.flush()).toEqual(['and it will take a while, I think.']);
  });

  it('does not make a clip of a short opening word or cut inside a number', () => {
    expect(sentences('Okay, I started the task and will tell you when it is done.')).toEqual(['Okay, I started the task and will tell you when it is done.']);
    expect(sentences('Sure, the folder holds 1,250 files, most of them logs.')).toEqual(['Sure, the folder holds 1,250 files,', 'most of them logs.']);
    expect(sentences('Everything went well this time. Here is what was done today:\n- listed the folder first\n- read the main script next')).toEqual([
      'Everything went well this time.',
      'Here is what was done today:',
      '- listed the folder first',
      '- read the main script next',
    ]);
  });

  it('cuts a very long run without a sentence end at a comma', () => {
    const long = Array.from({ length: 60 }, (_, i) => `item number ${i}`).join(', ');
    const pieces = sentences(long);
    expect(pieces.length).toBeGreaterThan(2);
    expect(pieces.every((p) => p.length <= 320)).toBe(true);
    expect(pieces.join(' ')).toBe(long);
  });
});
