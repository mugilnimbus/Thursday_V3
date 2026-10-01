/* Screen-level UI state shared by the shell: the open dialog, the open chat session, and whether
   the app is at phone width (where the side panel becomes a bottom tab bar). */

import { app } from './app.svelte';
import { ChatSession } from './chat.svelte';

export type DialogState =
  | { kind: 'rename-chat'; chatId: string }
  | { kind: 'delete-chat'; chatId: string }
  | { kind: 'delete-project'; projectId: string };

/** A yes/no question shown in the app's own dialog (browser popups are blocked in embedded panes). */
export interface Question {
  title: string;
  body: string;
  action: string;
  danger?: boolean;
  resolve: (yes: boolean) => void;
}

export const NARROW_PX = 760;

class Ui {
  dialog = $state<DialogState | null>(null);
  question = $state<Question | null>(null);
  session = $state<ChatSession | null>(null);
  width = $state(window.innerWidth);
  narrow = $derived(this.width <= NARROW_PX);

  constructor() {
    window.addEventListener('resize', () => (this.width = window.innerWidth));
  }

  /** Ask before a destructive or discarding action. Resolves true only when the user confirms. */
  ask(question: Omit<Question, 'resolve'>): Promise<boolean> {
    this.question?.resolve(false);
    return new Promise((resolve) => (this.question = { ...question, resolve }));
  }

  answer(yes: boolean): void {
    this.question?.resolve(yes);
    this.question = null;
  }

  openChat(chatId: string): ChatSession {
    if (this.session?.chatId === chatId) return this.session;
    this.session?.dispose();
    const session = new ChatSession(chatId, app.stream);
    this.session = session;
    void session.load();
    return session;
  }

  closeChat(): void {
    this.session?.dispose();
    this.session = null;
  }
}

export const ui = new Ui();
