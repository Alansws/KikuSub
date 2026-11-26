/**
 * 监看区高度偏好（2026-11-24 Phase 2）。
 *
 * 视频区改成「可拖高的暗底舞台」之后，高度是一个纯界面偏好，和侧栏折叠
 * （`sidebarPrefs`）、波形高度同层：不进工作区历史、不参与任何转写或导出。
 *
 * 为什么不塞进 `ReviewView.svelte`：那个文件有行数预算（红线 11，只许变短），
 * 而这里除了存取偏好还有两条纯计算（上限、状态条文案），都能单测。
 *
 * 语义：`height = 0` 表示「按 16:9 自然高度」，不是「高度 0」。拖到 0 也存 0，
 * 也就是「恢复默认」——双击分隔条走的就是这条路。
 */

const STORAGE_KEY = 'kikusub.stageHeight';

/** 拖高上限的窗口占比：留下时间轴、走带与至少 6 行表格的可视高度。 */
export const STAGE_MAX_RATIO = 0.55;

/** 不低于这个高度才有意义（再矮就只剩一条黑边）。 */
export const STAGE_MIN_H = 160;

export interface MediaLike {
  proxy_ready?: boolean;
  needs_proxy?: boolean;
  video_width?: number;
  video_height?: number;
  video_codec?: string;
}

/** 从 localStorage 读初始高度；坏值一律当 0（= 默认），不让脏数据把布局卡死。 */
export function readStageHeight(): number {
  try {
    const raw = Number(localStorage.getItem(STORAGE_KEY) || 0);
    return Number.isFinite(raw) && raw > 0 ? Math.min(900, Math.round(raw)) : 0;
  } catch {
    return 0;
  }
}

export function saveStageHeight(height: number): void {
  try {
    localStorage.setItem(STORAGE_KEY, String(height));
  } catch {
    /* 隐私模式 / 配额满了：记不住偏好不影响本次使用 */
  }
}

/** 拖拽时把目标高度夹进可用区间。`<= 0` 表示「恢复默认」。 */
export function clampStageHeight(height: number, viewportH: number): number {
  if (!Number.isFinite(height) || height <= 0) return 0;
  const cap = Math.max(STAGE_MIN_H, Math.round(viewportH * STAGE_MAX_RATIO));
  return Math.round(Math.max(STAGE_MIN_H, Math.min(cap, height)));
}

/** 窗口高度 → 拖高上限（供分隔条直接用）。 */
export function stageMaxHeight(viewportH: number): number {
  if (!Number.isFinite(viewportH) || viewportH <= 0) return 720;
  return Math.max(STAGE_MIN_H, Math.round(viewportH * STAGE_MAX_RATIO));
}

/** 状态条左边的代理文案。 */
export function proxyLabel(media: MediaLike | null | undefined): string {
  if (!media) return '';
  if (media.proxy_ready) return '480p 监看代理已就绪';
  if (media.needs_proxy) return '建议压制监看代理';
  return '原始画面';
}

/** 状态条中段的分辨率 / 编码，例如 `1080×1920 · H264`。 */
export function mediaResolution(media: MediaLike | null | undefined): string {
  if (!media) return '';
  const size =
    media.video_width && media.video_height
      ? `${media.video_width}×${media.video_height}`
      : '';
  const codec = String(media.video_codec || '').toUpperCase();
  return [size, codec].filter(Boolean).join(' · ');
}
