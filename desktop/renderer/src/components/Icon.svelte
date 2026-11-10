<script lang="ts">
  /**
   * 图标：内联 SVG，模拟 SF Symbols 的线条风格。
   * 零 emoji 是这次改造里收益/成本比最高的一条（见规划 §6）。
   */
  let { name, size = 15 }: { name: string; size?: number } = $props();

  const STROKE: Record<string, string> = {
    tray: '<path d="M2 9.5V12a1.5 1.5 0 0 0 1.5 1.5h9A1.5 1.5 0 0 0 14 12V9.5"/><path d="M2 9.5h3l1 2h4l1-2h3"/><path d="M8 2v5.5"/><path d="M5.8 5.3 8 7.5l2.2-2.2"/>',
    wave: '<path d="M1.5 8h1.2"/><path d="M4.2 5.4v5.2"/><path d="M6.6 3.2v9.6"/><path d="M9 6v4"/><path d="M11.4 4.2v7.6"/><path d="M13.8 6.6v2.8"/>',
    listcheck:
      '<path d="M2 4h1.6"/><path d="M2 8h1.6"/><path d="M2 12h1.6"/><path d="M6 4h8"/><path d="M6 8h8"/><path d="M6 12h4"/><path d="M11.6 11.6 12.8 12.8 15 10"/>',
    doc: '<path d="M9.2 1.8H4.5A1.5 1.5 0 0 0 3 3.3v9.4a1.5 1.5 0 0 0 1.5 1.5h7a1.5 1.5 0 0 0 1.5-1.5V5.3z"/><path d="M9.2 1.8v3.5H13"/><path d="M5.6 8.6h4.8"/><path d="M5.6 11h3.2"/>',
    save: '<path d="M3.2 2.4h7.6L13.6 5v7a1.6 1.6 0 0 1-1.6 1.6H4A1.6 1.6 0 0 1 2.4 12V4a1.6 1.6 0 0 1 1.6-1.6z"/><path d="M5.2 2.4v3.4h5.2V2.4"/><rect x="4.8" y="8.6" width="6.4" height="5" rx=".8"/>',
    gear: '<circle cx="8" cy="8" r="2.1"/><path d="M8 1.6v1.6M8 12.8v1.6M14.4 8h-1.6M3.2 8H1.6M12.5 3.5l-1.1 1.1M4.6 11.4l-1.1 1.1M12.5 12.5l-1.1-1.1M4.6 4.6 3.5 3.5"/>',
    moon: '<path d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8 5.6 5.6 0 1 0 13.2 9.6z"/>',
    sidebar:
      '<rect x="1.8" y="2.8" width="12.4" height="10.4" rx="2"/><path d="M6.2 2.8v10.4"/>',
    film: '<rect x="2" y="3.4" width="12" height="9.2" rx="1.6"/><path d="M5.4 3.4v9.2M10.6 3.4v9.2M2 6.4h3.4M2 9.6h3.4M10.6 6.4H14M10.6 9.6H14"/>',
    search: '<circle cx="7.2" cy="7.2" r="4.4"/><path d="M10.6 10.6 13.6 13.6"/>',
    warn: '<path d="M8 4.4v4.2"/><circle cx="8" cy="11.4" r=".85" fill="currentColor" stroke="none"/>',
    check: '<path d="M3 8.4 6.3 11.7 13 5"/>',
    folder:
      '<path d="M1.8 4.6a1.4 1.4 0 0 1 1.4-1.4h2.6l1.4 1.6h5.6a1.4 1.4 0 0 1 1.4 1.4v5.4a1.4 1.4 0 0 1-1.4 1.4H3.2a1.4 1.4 0 0 1-1.4-1.4z"/>',
    undo: '<path d="M4.2 6.2H10a3.8 3.8 0 0 1 0 7.6H6.4"/><path d="M6.6 3.8 4.2 6.2l2.4 2.4"/>',
    redo: '<path d="M11.8 6.2H6a3.8 3.8 0 0 0 0 7.6h3.6"/><path d="M9.4 3.8l2.4 2.4-2.4 2.4"/>',
    trash: '<path d="M2.8 4.4h10.4"/><path d="M6.4 4.4V3.2a1 1 0 0 1 1-1h1.2a1 1 0 0 1 1 1v1.2"/><path d="M4.4 4.4l.6 8a1.2 1.2 0 0 0 1.2 1.1h3.6a1.2 1.2 0 0 0 1.2-1.1l.6-8"/>',
    export: '<path d="M8 1.8v8.4"/><path d="M5.2 7.4 8 10.2l2.8-2.8"/><path d="M2.6 11.4v1.2a1.4 1.4 0 0 0 1.4 1.4h8a1.4 1.4 0 0 0 1.4-1.4v-1.2"/>',
    plus: '<path d="M8 3v10"/><path d="M3 8h10"/>',
    minus: '<path d="M3 8h10"/>',
    close: '<path d="M4.2 4.2 11.8 11.8"/><path d="M11.8 4.2 4.2 11.8"/>',
    'chevron-left': '<path d="M10 3.5 5.5 8 10 12.5"/>',
    'chevron-right': '<path d="M6 3.5 10.5 8 6 12.5"/>',
    target:
      '<circle cx="8" cy="8" r="5.2"/><circle cx="8" cy="8" r="1.4" fill="currentColor" stroke="none"/><path d="M8 1v2M8 13v2M1 8h2M13 8h2"/>',
  };

  const FILL: Record<string, string> = {
    play: '<path d="M5.2 3.1c0-.6.66-.98 1.18-.66l6.2 3.9c.5.32.5 1.05 0 1.37l-6.2 3.9A.78.78 0 0 1 5.2 11z"/>',
    pause:
      '<rect x="4" y="3" width="2.6" height="10" rx=".9"/><rect x="9.4" y="3" width="2.6" height="10" rx=".9"/>',
    stop: '<rect x="4" y="4" width="8" height="8" rx="1.6"/>',
  };
</script>

{#if FILL[name]}
  <svg viewBox="0 0 16 16" width={size} height={size} fill="currentColor" aria-hidden="true">
    {@html FILL[name]}
  </svg>
{:else}
  <svg
    viewBox="0 0 16 16"
    width={size}
    height={size}
    fill="none"
    stroke="currentColor"
    stroke-width="1.4"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    {@html STROKE[name] ?? ''}
  </svg>
{/if}

<style>
  svg {
    display: block;
    flex: 0 0 auto;
  }
</style>
