<!-- A small button that copies a piece of text, and shows a tick for a moment once it has. -->
<script lang="ts">
  import { copyText } from './copy';
  import Icon from './Icon.svelte';

  let { text, what = 'message' }: { text: string; what?: string } = $props();

  let copied = $state(false);
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function copy(event: MouseEvent) {
    event.stopPropagation();
    if (!(await copyText(text))) return;
    copied = true;
    clearTimeout(timer);
    timer = setTimeout(() => (copied = false), 1600);
  }
</script>

<button class="copy" class:done={copied} type="button" onclick={copy} aria-label={copied ? 'Copied' : `Copy ${what}`} title={copied ? 'Copied' : `Copy ${what}`}>
  <Icon name={copied ? 'check' : 'copy'} size={16} />
</button>
