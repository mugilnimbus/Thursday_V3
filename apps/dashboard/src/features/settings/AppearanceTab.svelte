<script lang="ts">
  import { prefs } from '../../lib/state/prefs.svelte';
</script>

<div class="cols-auto" style="max-width:640px">
  <button class="theme-choice" aria-pressed={prefs.theme === 'black'} onclick={() => prefs.setTheme('black')}>
    <span class="swatch" style="background:#000;border-color:#463d5c"></span><b>Black</b><span class="caption">Default</span>
  </button>
  <button class="theme-choice" aria-pressed={prefs.theme === 'white'} onclick={() => prefs.setTheme('white')}>
    <span class="swatch" style="background:#fff;border-color:#d9d2e6"></span><b>White</b><span class="caption">Lavender panels, heavier text</span>
  </button>
</div>
<div class="switch-row" style="max-width:640px">
  <span>Face animation<br /><span class="caption">A face made of particles appears in a chat while Thursday listens, thinks and speaks. The line along the bottom stays either way.</span></span>
  <input type="checkbox" class="switch" aria-label="Face animation" checked={prefs.voiceFace} onchange={(e) => prefs.setVoiceFace(e.currentTarget.checked)} />
</div>
<p class="caption" style="margin:0">Saved in this browser only.</p>
