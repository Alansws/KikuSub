/**
 * 设置页「环境与诊断 → 路径管理」的分组。
 *
 * 现状是 11 条路径平铺在一个列表里；重构后只把交付物相关的 3 条放在明面，
 * 其余 8 条折进「其余内部路径」。
 *
 * 这条边界必须是**代码里的一处**，不是模板里的 if：加一条路径时如果忘了分组，
 * 它既不会出现在明面也不会出现在折叠区，等于静默消失。测试会核对 3+8 覆盖全部 11 条。
 */

export type PathKey =
  | 'output_dir'
  | 'export_dir'
  | 'video_export_dir'
  | 'models_dir'
  | 'presets_path'
  | 'settings_path'
  | 'proxy_dir'
  | 'tts_cache_dir'
  | 'voices_dir'
  | 'tts_model_dir'
  | 'log_dir';

export interface PathRowSpec {
  key: PathKey;
  label: string;
  /** 一行说明，只在折叠区与需要解释的行上显示。 */
  hint: string;
}

/** 可以改、且会写进 settings.json 的 3 条。 */
export const EDITABLE_PATHS: PathRowSpec[] = [
  {
    key: 'export_dir',
    label: '导出文件夹',
    hint: '字幕 SRT / VTT / TXT 的默认落点',
  },
  {
    key: 'video_export_dir',
    label: '成片目录',
    hint: '硬字幕 / 软字幕成片的落点，可独立于字幕',
  },
  {
    key: 'models_dir',
    label: '模型目录',
    hint: '权重、CTC 对齐头与标点模型；切换会重启内核',
  },
];

/** 只读的内部路径：默认折叠，避免把「会写文件的文件夹」摊满一屏。 */
export const INTERNAL_PATHS: PathRowSpec[] = [
  { key: 'output_dir', label: '运行数据目录', hint: '草稿、任务报告与最近字幕' },
  { key: 'proxy_dir', label: '代理缓存', hint: '手动压制的 480p 代理，可随时清空' },
  { key: 'tts_cache_dir', label: 'TTS 缓存', hint: '朗读合成结果，删掉会自动重建' },
  { key: 'voices_dir', label: '克隆音色', hint: '参考音频与克隆资产' },
  { key: 'tts_model_dir', label: 'TTS 模型', hint: 'OmniVoice 权重' },
  { key: 'log_dir', label: '日志目录', hint: 'kikusub.log 与轮转备份' },
  { key: 'presets_path', label: '预设文件', hint: 'presets.json' },
  { key: 'settings_path', label: '设置文件', hint: 'settings.json（不含 AI Key）' },
];

export const ALL_PATHS: PathRowSpec[] = [...EDITABLE_PATHS, ...INTERNAL_PATHS];

export function allPathKeys(): PathKey[] {
  return ALL_PATHS.map((row) => row.key);
}

/** 从 SettingsPayload['paths'] 里取显示值；缺失时给空字符串（组件显示破折号）。 */
export function pathValue(
  paths: Record<string, string | undefined> | null | undefined,
  key: PathKey,
): string {
  return paths?.[key] ?? '';
}

/** 成片目录是「跟随导出文件夹」还是自定义：空字符串 = 跟随（后端约定）。 */
export function videoFollowsExport(videoExportSetting: string | null | undefined): boolean {
  return !String(videoExportSetting ?? '').trim();
}

export function isCustomDir(
  settings: { export_dir?: string; video_export_dir?: string } | null | undefined,
  key: 'export_dir' | 'video_export_dir',
): boolean {
  if (key === 'video_export_dir') return !videoFollowsExport(settings?.video_export_dir);
  return Boolean(String(settings?.export_dir ?? '').trim());
}

/** 行尾的小标记：`自定义` / `默认` / 空。 */
export function pathBadge(
  settings: { export_dir?: string; video_export_dir?: string } | null | undefined,
  key: 'export_dir' | 'video_export_dir',
): string {
  return isCustomDir(settings, key) ? '自定义' : '默认';
}

/** 成片目录的显示值：跟随时显示「跟随导出文件夹」，否则显示真实路径。 */
export function videoExportDisplay(
  videoExportSetting: string | null | undefined,
  resolvedPath: string,
): string {
  return videoFollowsExport(videoExportSetting) ? '跟随导出文件夹' : resolvedPath;
}
