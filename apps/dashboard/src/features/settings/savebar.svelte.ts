/* The Settings save bar: the active tab reports whether it has unsaved edits and how to save or
   discard them; the bar appears only while something is unsaved. */

export class SaveBar {
  dirty = $state(false);
  saving = $state(false);
  error = $state('');
  save: () => Promise<void> = async () => undefined;
  discard: () => void = () => undefined;

  attach(handlers: { save: () => Promise<void>; discard: () => void }): () => void {
    this.save = handlers.save;
    this.discard = handlers.discard;
    return () => {
      this.dirty = false;
      this.error = '';
      this.save = async () => undefined;
      this.discard = () => undefined;
    };
  }
}
