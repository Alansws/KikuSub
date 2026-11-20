/**
 * 导出面板的文案标签（纯函数，无状态）。
 *
 * 从 `store.svelte.ts` 拆出来：`editExportUi` 的历史步骤说明要拼这些标签，
 * 而它们只是「key → 人话」的映射。拆走后 store 不再为每次新增档位变长。
 */

export function shortPath(path: string): string {
  if (!path) return '—';
  const parts = path.split('/').filter(Boolean);
  return parts.length ? parts[parts.length - 1] : path;
}

export function exportModeLabel(mode: string): string {
  return (
    ({ burn: '烧录硬字幕', soft: '软字幕 MP4', copy: '仅封装' } as Record<string, string>)[mode] ?? mode
  );
}

export function exportTrackLabel(track: string): string {
  return ({ source: '原文', target: '译文', both: '双语' } as Record<string, string>)[track] ?? track;
}

export function exportResolutionLabel(resolution: string): string {
  return resolution === 'source' ? '原始' : resolution;
}

export function exportQualityLabel(
  preset: string,
  presets: { key: string; label: string }[] = [],
): string {
  return (
    presets.find((item) => item.key === preset)?.label ??
    ({ small: '小', balanced: '甜点', high: '高', ultra: '极高' } as Record<string, string>)[preset] ??
    preset
  );
}
