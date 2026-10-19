/* Saving in Settings: the active tab reports whether it has unsaved edits and how to save or discard them.
   Save and Discard sit at the top right of Settings, beside the tabs, and appear only while something is unsaved. */

import { errorText } from '../../lib/state/app.svelte';

export const SAVE_LABEL = 'Save changes';

export class SaveBar {
  dirty = $state(false);
  saving = $state(false);
  error = $state('');
  /** What the save button says; a tab may name what saving makes ("Save as version 3"). */
  label = $state(SAVE_LABEL);
  save: () => Promise<void> = async () => undefined;
  discard: () => void = () => undefined;

  attach(handlers: { save: () => Promise<void>; discard: () => void }): () => void {
    this.save = handlers.save;
    this.discard = handlers.discard;
    return () => {
      this.dirty = false;
      this.error = '';
      this.label = SAVE_LABEL;
      this.save = async () => undefined;
      this.discard = () => undefined;
    };
  }

  /** Save now. True when it worked; otherwise the reason is in `error` and the edits stay. */
  async run(): Promise<boolean> {
    this.saving = true;
    this.error = '';
    try {
      await this.save();
      return true;
    } catch (e) {
      this.error = errorText(e);
      return false;
    } finally {
      this.saving = false;
    }
  }
}
