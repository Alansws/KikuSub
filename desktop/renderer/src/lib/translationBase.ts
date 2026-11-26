/**
 * 「只动句读」的原文改动：把服务端静默对齐过的译文 base 套到本地轨上。
 *
 * 为什么在这里：批量清理标点 / 手工补一个句号之后，服务端已经把 `base` 更新成
 * 新原文（见 `core/i18n.rebase_punctuation_base`），本地这份 `app.translations`
 * 还是旧的 base，不对齐就会继续显示「N 条待更新」。
 *
 * 为什么不重拉 `/api/translations`：那会 bump `translationsRevision`，右侧检查器
 * 正在编辑的输入框会被服务端文本回灌，用户刚敲的字就没了。这里只改 base，
 * 不动 revision —— stale 由 `$derived` 读取 base，会自己重算。
 *
 * 纯函数 + 零运行时 import（`node --test` 能直接加载），单测在同名 `.test.mjs`。
 */
import type { TranslationTrack } from './api';

export interface RebaseCue {
  text: string;
}

export function applyRebasedBases(
  tracks: Record<string, TranslationTrack>,
  cues: ArrayLike<RebaseCue>,
  rebased: Record<string, number[]> | undefined | null,
): number {
  if (!rebased) return 0;
  let applied = 0;
  for (const [lang, indices] of Object.entries(rebased)) {
    const track = tracks[lang];
    if (!track?.base || !Array.isArray(indices)) continue;
    for (const index of indices) {
      if (!Number.isInteger(index) || index < 0 || index >= track.base.length) continue;
      const text = cues[index]?.text;
      if (typeof text !== 'string') continue;
      track.base[index] = text;
      applied += 1;
    }
  }
  return applied;
}
