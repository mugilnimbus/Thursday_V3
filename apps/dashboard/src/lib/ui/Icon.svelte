<script lang="ts">
  let { name, size, class: extra = '' }: { name: string; size?: number; class?: string } = $props();
</script>

<svg class="icon {extra}" aria-hidden="true" style:width={size ? `${size}px` : undefined} style:height={size ? `${size}px` : undefined}>
  <use href="#i-{name}" />
</svg>
