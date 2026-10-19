/* Cut a reply into pieces to read aloud one after another.

   Making the audio takes about a fifth of the time the audio lasts, so the wait before the voice starts is set by
   how long the first piece is: a whole reply takes several seconds, a sentence about one, a short clause under
   half a second. So a reply is spoken piece by piece, and the next piece is prepared while one plays. The feed
   also works on a reply that is still being written: text goes in as it arrives and complete pieces come out.

   A piece ends after . ! or ? followed by a space, or at a line break. Short pieces join the next one, so "Okay."
   is not a clip of its own, and a number list ("1. First") or an abbreviation ("e.g. this") does not end a piece.
   The first piece of a reply may also end at a comma, semicolon or colon, which gets the voice started sooner;
   after that pieces are whole sentences, which sound better. */

const MIN_CHARS = 24;
const MAX_CHARS = 320;
const QUICK_MIN_CHARS = 16; // the shortest opening clause worth a clip of its own
const END = /([.!?]+["')\]]*)(\s+)|([,;:])[ \t]+|\n+/g; // a clause mark before a line break is left to the line break
const ABBREVIATIONS = new Set(['e.g', 'i.e', 'etc', 'vs', 'mr', 'mrs', 'ms', 'dr', 'no', 'fig', 'approx']);

/** Whether a piece has anything a voice can say (not only punctuation or markdown marks). */
export function sayable(piece: string): boolean {
  return /[\p{L}\p{N}]/u.test(piece);
}

function endsSentence(before: string): boolean {
  const word = (before.match(/(\S+)$/)?.[1] ?? '').replace(/["')\]]+$/, '').replace(/[.!?]+$/, '');
  if (/^\d+$/.test(word)) return false; // "1." in a numbered list
  if (/^[A-Za-z]$/.test(word)) return false; // an initial: "J. Smith"
  return !ABBREVIATIONS.has(word.toLowerCase());
}

export class SentenceFeed {
  private rest = '';
  private started = false; // the reply's first piece has been given out

  /** Add text as it arrives. Returns the pieces that are now complete. */
  push(text: string): string[] {
    this.rest += text;
    return this.take(false);
  }

  /** The reply is over: whatever is left is the last piece. */
  flush(): string[] {
    return this.take(true);
  }

  private take(final: boolean): string[] {
    const pieces: string[] = [];
    let start = 0;
    const give = (piece: string) => {
      pieces.push(piece); // one with nothing to say in it (a rule, a code fence) is dropped below
      this.started ||= sayable(piece);
    };
    END.lastIndex = 0;
    for (let m = END.exec(this.rest); m; m = END.exec(this.rest)) {
      const end = m.index + m[0].length;
      if (m[3]) {
        // A clause: only the opening of a reply is cut here.
        const clause = this.rest.slice(start, m.index + 1);
        if (this.started || !sayable(clause) || clause.trim().length < QUICK_MIN_CHARS) continue;
        give(clause);
        start = end;
        continue;
      }
      if (end === this.rest.length && !final && !m[0].includes('\n')) break; // more of this sentence's space may come
      const mark = m[1] ? m.index + m[1].length : m.index;
      const piece = this.rest.slice(start, mark);
      if (m[1] && !endsSentence(piece)) continue;
      if (sayable(piece) && piece.trim().length < MIN_CHARS) continue; // too short alone: joins the next
      give(piece);
      start = end;
    }
    this.rest = this.rest.slice(start);
    // A long run with no sentence end (a list on one line, a long clause) is cut at the last comma or space.
    while (this.rest.length > MAX_CHARS) {
      const window = this.rest.slice(0, MAX_CHARS);
      const cut = Math.max(window.lastIndexOf(', '), window.lastIndexOf('; ')) + 1 || window.lastIndexOf(' ') + 1 || MAX_CHARS;
      give(this.rest.slice(0, cut));
      this.rest = this.rest.slice(cut);
    }
    if (final && this.rest.trim()) {
      give(this.rest);
      this.rest = '';
    }
    return pieces.map((p) => p.replace(/\s+/g, ' ').trim()).filter(sayable);
  }
}

/** A whole reply as its pieces. */
export function sentences(text: string): string[] {
  const feed = new SentenceFeed();
  return [...feed.push(text), ...feed.flush()];
}
