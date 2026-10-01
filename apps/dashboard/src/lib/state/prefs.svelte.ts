/* Per-browser conveniences: theme, side panel width, the face animation switch, and message drafts.
   Stored in localStorage, which can be unavailable (private windows, blocked storage), so every
   access is guarded and the app works without it. */

export type Theme = 'black' | 'white';

export const NAV_MIN = 200;
export const NAV_MAX = 440;

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: keep the value for this session only */
  }
}

class Prefs {
  theme = $state<Theme>(read('thursday.theme') === 'white' ? 'white' : 'black');
  navWidth = $state<number | null>(Number(read('thursday.navWidth')) || null);
  /** Show the particle face while the voice agent listens, thinks and speaks. The line stays either way. */
  voiceFace = $state(read('thursday.voiceFace') !== 'off');

  setTheme(theme: Theme): void {
    this.theme = theme;
    document.documentElement.dataset.theme = theme;
    write('thursday.theme', theme);
  }

  setVoiceFace(on: boolean): void {
    this.voiceFace = on;
    write('thursday.voiceFace', on ? null : 'off');
  }

  setNavWidth(width: number | null): void {
    this.navWidth = width === null ? null : Math.round(Math.min(NAV_MAX, Math.max(NAV_MIN, width)));
    write('thursday.navWidth', this.navWidth === null ? null : String(this.navWidth));
  }

  draft(chatId: string): string {
    return read(`thursday.draft.${chatId}`) ?? '';
  }

  saveDraft(chatId: string, text: string): void {
    write(`thursday.draft.${chatId}`, text.trim() ? text : null);
  }
}

export const prefs = new Prefs();
document.documentElement.dataset.theme = prefs.theme;
