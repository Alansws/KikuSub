/**
 * 字幕剪贴板：把「已经转写正确的一句」复制到另一个播放头位置。
 *
 * 典型场景（2026-11-17 用户需求）：吸气 / 呼气这类气声很轻，局部转写经常空结果，
 * 偶尔转出来一条正确的，就希望把那一句原样搬到第二处、第三处。
 *
 * 设计约束：
 * - 复制的是「原文 + 时长 + 各语种译文（含 base）」，粘贴时新建一条；
 * - 起点 = 播放头，长度沿用原句；只有片尾不够长时才缩短；
 * - 与邻句重叠只提示，不自动改邻句时间轴；
 * - 一次插入只压一步服务端历史，⌘Z 能把原文与译文一起退回；
 * - 剪贴板跨片保留，但粘贴只写当前会话已存在的译文轨（缺轨静默忽略）；
 * - 快捷键与检查器按钮共用本模块，并先 `flushCueDraft()`，避免复制到未提交的旧文本。
 */

import { api } from './api';
import { flushCueDraft } from './cueDraftCommit';
import { clipSummary, planCuePaste, type CueClip } from './cueClip';
import {
  app,
  applyCueSnapshot,
  loadTranslations,
  play,
  scheduleDraftSave,
  toast,
} from './store.svelte';
import { comboOf, formatCombo } from './shortcuts.svelte';
import { tcShort } from './time';

const round3 = (value: number) => Math.round(value * 1000) / 1000;

/** 应用内字幕剪贴板。跨片保留；重启应用后清空（系统剪贴板里的纯文本还在）。 */
export const cueClip = $state<{ value: CueClip | null }>({ value: null });

const copyCombo = () => formatCombo(comboOf('review.copyCue'));
const pasteCombo = () => formatCombo(comboOf('review.pasteCue'));

/** 同时写系统剪贴板，方便把同一句粘到别的软件；失败不影响应用内粘贴。 */
async function writeSystemClipboard(text: string): Promise<void> {
  try {
    if (window.kikusub?.writeClipboard) {
      await window.kikusub.writeClipboard(text);
    } else if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
    }
  } catch {
    /* 剪贴板权限 / 无头环境：应用内剪贴板仍然可用 */
  }
}

/** 复制第 `index` 条字幕（默认当前选中行）。 */
export async function copyCueAt(index = play.selected): Promise<boolean> {
  await flushCueDraft();
  if (!app.media) {
    toast('请先导入媒体', 'warn');
    return false;
  }
  const cue = app.cues[index];
  if (!cue) {
    toast('先选中一条字幕再复制', 'warn');
    return false;
  }
  if (!cue.text.trim()) {
    toast('这条字幕是空的，没有可复制的文本', 'warn');
    return false;
  }

  const translations: CueClip['translations'] = {};
  for (const [lang, track] of Object.entries(app.translations)) {
    const text = track.texts[index] ?? '';
    if (!text.trim()) continue;
    translations[lang] = { text, base: track.base[index] ?? text };
  }

  const clip: CueClip = {
    text: cue.text,
    duration: round3(cue.end - cue.start),
    translations,
    sourceStart: cue.start,
  };
  cueClip.value = clip;
  await writeSystemClipboard(cue.text);
  toast(`已复制${clipSummary(clip)}。把播放头移到目标位置，按 ${pasteCombo()} 粘贴。`);
  return true;
}

/** 供 App.svelte 快捷键调用：复制当前选中行。 */
export function copySelectedCue(): Promise<boolean> {
  return copyCueAt(play.selected);
}

let pasting = false;

/**
 * 在 `at`（默认播放头）粘贴字幕。
 *
 * 只切选中与滚动，**不 seek、不改缩放**：用户刚刚把播放头放到目标位置，
 * 粘贴后再把播放头挪走只会让人多调一次。
 */
export async function pasteCueAt(at = play.time): Promise<number> {
  if (pasting) return -1;
  pasting = true;
  try {
    await flushCueDraft();
    if (!app.media) {
      toast('请先导入媒体', 'warn');
      return -1;
    }
    const clip = cueClip.value;
    if (!clip) {
      toast(`字幕剪贴板是空的：先选中一条字幕按 ${copyCombo()} 复制`, 'warn');
      return -1;
    }

    const result = planCuePaste({
      at,
      length: clip.duration,
      cues: app.cues,
      mediaDuration: app.media.duration || 0,
    });
    if (!result.ok) {
      toast(result.reason, 'warn');
      return -1;
    }
    const { start, end, index, overlapCount, overlapSeconds, clamped } = result.plan;

    // 剪贴板可能来自另一部片：只提交当前会话确实存在的语种。
    const translations: Record<string, { text: string; base: string }> = {};
    for (const [lang, item] of Object.entries(clip.translations)) {
      if (!app.translations[lang]) continue;
      translations[lang] = { text: item.text, base: item.base };
    }

    const data = await api.insertCue(index, {
      start,
      end,
      text: clip.text,
      label: `粘贴字幕到 ${tcShort(start)}`,
      translations,
    });
    applyCueSnapshot(data);
    await loadTranslations();
    scheduleDraftSave();

    // 选中新句并强制表格滚过去；不 seek、不改缩放，也不抢文本框焦点
    //（抢了焦点后下一次 ⌘⇧V 会被「输入框内让位」规则挡掉）。
    play.selected = data.index;
    play.selectNonce += 1;

    const notes: string[] = [];
    if (clamped) notes.push(`片尾只剩 ${round3(end - start).toFixed(2)} 秒，已缩短`);
    if (overlapCount) {
      notes.push(
        `与 ${overlapCount} 条已有字幕重叠 ${overlapSeconds.toFixed(2)} 秒，可拖动调整`,
      );
    }
    const suffix = notes.length ? ` ${notes.join('；')}。` : ' ';
    toast(
      `已在 ${tcShort(start)} 粘贴${clipSummary(clip)}。${suffix}⌘Z 可撤销`,
      notes.length ? 'warn' : 'info',
    );
    return data.index;
  } catch (err) {
    toast(`粘贴字幕失败：${(err as Error).message}`, 'error');
    return -1;
  } finally {
    pasting = false;
  }
}

/** 供 App.svelte 快捷键调用：粘贴到播放头。 */
export function pasteCueAtPlayhead(): Promise<number> {
  return pasteCueAt(play.time);
}

/** 清空应用内字幕剪贴板（系统剪贴板不动）。 */
export function clearCueClip() {
  cueClip.value = null;
  toast('字幕剪贴板已清空');
}
