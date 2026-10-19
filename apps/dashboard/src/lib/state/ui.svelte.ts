/* Screen-level UI state shared by the shell: the open dialog, the open chat session, and whether
   the app is at phone width (where the side panel becomes a bottom tab bar). */

import { app } from './app.svelte';
import { ChatSession } from './chat.svelte';

export type DialogState =
  | { kind: 'rename-chat'; chatId: string }
  | { kind: 'delete-chat'; chatId: string }
  | { kind: 'delete-project'; projectId: string };

export type Answer = 'yes' | 'no' | 'save';

/** A question shown in the app's own dialog (browser popups are blocked in embedded panes). Usually yes or no;
    with `save`, a third button that keeps the work instead of dropping it. */
export interface Question {
  title: string;
  body: string;
  action: string;
  danger?: boolean;
  /** Label of the save button; the dialog then offers Cancel, the action, and this. */
  save?: string;
  resolve: (answer: Answer) => void;
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
  ask(question: Omit<Question, 'resolve' | 'save'>): Promise<boolean> {
    this.question?.resolve('no');
    return new Promise((resolve) => (this.question = { ...question, resolve: (answer) => resolve(answer === 'yes') }));
  }

  /** Before leaving unsaved edits: save them, discard them, or stay where you are. */
  askUnsaved(body: string, save = 'Save changes'): Promise<'save' | 'discard' | 'cancel'> {
    this.question?.resolve('no');
    return new Promise((resolve) => {
      this.question = {
        title: 'Unsaved changes',
        body,
        action: 'Discard',
        danger: true,
        save,
        resolve: (answer) => resolve(answer === 'save' ? 'save' : answer === 'yes' ? 'discard' : 'cancel'),
      };
    });
  }

  answer(answer: boolean | 'save'): void {
    this.question?.resolve(answer === 'save' ? 'save' : answer ? 'yes' : 'no');
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
