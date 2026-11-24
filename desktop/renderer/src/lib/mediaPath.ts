/**
 * 媒体路径的纯判断（2026-11-24 从 `store.svelte.ts` 抽出）。
 *
 * 只有一行逻辑，但 store 有行数预算（红线 11，只许变短）：加设置浮层时用掉了几行，
 * 把这类纯函数搬出来比把代码压成一行更干净。
 */

const SUBTITLE_EXTS = ['.srt', '.vtt'];

/** 这个路径是不是字幕文件（大小写无关）。 */
export function isSubtitlePath(path: string): boolean {
  const lower = String(path || '').toLowerCase();
  return SUBTITLE_EXTS.some((ext) => lower.endsWith(ext));
}

/** 成片导出的默认目录：视频导出目录 → 字幕导出目录 → 运行数据目录（逐级回退）。 */
export function pickVideoExportDir(config: {
  video_export_dir?: string;
  export_dir?: string;
  output_dir?: string;
} | null | undefined): string {
  return config?.video_export_dir || config?.export_dir || config?.output_dir || '';
}
