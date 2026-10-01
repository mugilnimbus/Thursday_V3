<!-- A QR code drawn as one SVG path. Always dark modules on white with a quiet zone, in both themes,
     because scanners need that contrast. -->
<script lang="ts">
  import qrcode from 'qrcode-generator';

  let { text, label }: { text: string; label: string } = $props();
  const QUIET = 4;

  const code = $derived.by(() => {
    const qr = qrcode(0, 'M'); // version chosen automatically; medium error correction
    qr.addData(text);
    qr.make();
    const n = qr.getModuleCount();
    let d = '';
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if (qr.isDark(y, x)) d += `M${x + QUIET} ${y + QUIET}h1v1h-1z`;
    return { d, size: n + QUIET * 2 };
  });
</script>

<svg class="qr-code" viewBox="0 0 {code.size} {code.size}" role="img" aria-label={label} shape-rendering="crispEdges">
  <rect width={code.size} height={code.size} fill="#fff" />
  <path d={code.d} fill="#000" />
</svg>

<style>
  .qr-code { width: 168px; height: 168px; flex: none; border-radius: var(--radius-md); }
</style>
