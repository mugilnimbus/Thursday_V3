<!-- Renders agent text as formatted elements. Everything is created as text nodes and known elements;
     model output is never inserted as HTML. -->
<script lang="ts">
  import CopyButton from './CopyButton.svelte';
  import { parse, type Span } from './markdown';

  let { text }: { text: string } = $props();
  const blocks = $derived(parse(text));
</script>

{#snippet spans(list: Span[])}
  {#each list as s, i (i)}{#if s.kind === 'text'}{s.text}{:else if s.kind === 'bold'}<strong>{@render spans(s.spans)}</strong>{:else if s.kind === 'italic'}<em>{@render spans(s.spans)}</em>{:else if s.kind === 'code'}<code>{s.text}</code>{:else}<a href={s.href} target="_blank" rel="noopener noreferrer nofollow">{s.text}</a>{/if}{/each}
{/snippet}

<div class="md">
  {#each blocks as b, i (i)}
    {#if b.kind === 'heading'}
      <p class="md-h" data-level={Math.min(b.level, 4)} role="heading" aria-level={Math.min(b.level + 2, 6)}>{@render spans(b.spans)}</p>
    {:else if b.kind === 'paragraph'}
      <p>{@render spans(b.spans)}</p>
    {:else if b.kind === 'list'}
      <svelte:element this={b.ordered ? 'ol' : 'ul'} start={b.ordered ? b.start : undefined}>
        {#each b.items as item, j (j)}<li>{@render spans(item)}</li>{/each}
      </svelte:element>
    {:else if b.kind === 'code'}
      <div class="code-block"><pre class="code">{b.text}</pre><CopyButton text={b.text} what="code" /></div>
    {:else if b.kind === 'table'}
      <!-- A wide table scrolls sideways inside its own box; the message never grows wider than the thread. -->
      <div class="md-table">
        <table>
          <thead>
            <tr>{#each b.head as cell, j (j)}<th data-align={b.align[j]}>{@render spans(cell)}</th>{/each}</tr>
          </thead>
          <tbody>
            {#each b.rows as row, r (r)}
              <tr>{#each row as cell, j (j)}<td data-align={b.align[j]}>{@render spans(cell)}</td>{/each}</tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <hr />
    {/if}
  {/each}
</div>
