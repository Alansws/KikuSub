/**
 * 章节 / 时刻点标记的渲染层状态（独立于两个大文件）。
 *
 * 服务端是唯一真源：每次增删改都整表提交（`POST /api/chapters`），回来的是
 * **已归一化**的列表 + 一步历史。这样：
 * - ⌘Z 走 `Session.history` 那条统一时间线，没有第二套撤销栈；
 * - 切换影片 / 重启后由服务端按媒体身份落盘恢复（`core/chapters.py`）；
 * - 前端不做时间排序/衔接计算，展示与导出永远同一口径。
 */

import { api, type ChapterMark } from './api';
import { autoChapterName, DEFAULT_CHAPTER_TEMPLATE, isAutoTitle, normalizeTemplate } from './chapterNaming';
import {
  beginDraft,
  readyError,
  setEdge,
  toMarkTimes,
  type ChapterDraft,
  type DraftEdge,
} from './chapterDraft';
import { app, play, seekTo, toast } from './store.svelte';
import { tcShort } from './time';

export const chapters = $state({
  marks: [] as ChapterMark[],
  /** 服务端算好的实际区间数（写入容器后播放器看到的段数）。 */
  layoutCount: 0,
  loading: false,
  saving: false,
  error: '',
  /** 当前列表属于哪部影片：换片时用来判断要不要清空。 */
  forPath: '',
  /** 核对台当前的时间选区（由 ReviewView 同步过来）：「将选区设为章节」要用。 */
  selection: null as { start: number; end: number } | null,
  /**
   * 章节草稿：把一个时刻点补成区间。
   *
   * 只在渲染层、不进服务端也不进历史——它没有「半个章节」这种持久化形态。
   * 纯逻辑在 `lib/chapterDraft.ts`（含最短 0.2 秒与端点越界的校验）。
   */
  draft: null as ChapterDraft | null,
});

export function chapterCount(): number {
  return chapters.marks.length;
}

/**
 * 请求序号：连续改名 / 连续删除时，较慢的旧响应不能把新列表盖回去。
 * （每次请求都带完整列表，所以「最后一个发出的」才是最新意图。）
 */
let loadSeq = 0;
let saveSeq = 0;

/** 新标记的短 id。不需要全局唯一，只需要在列表里可寻址。 */
function newId(): string {
  const rand = Math.random().toString(36).slice(2, 8);
  return `ch-${Date.now().toString(36)}-${rand}`;
}

function currentPath(): string {
  return app.media?.path ?? '';
}

/** 读服务端标记；换片后旧列表必须先清空，避免把上一部的章节画到新片上。 */
export async function loadChapters(force = false): Promise<void> {
  const path = currentPath();
  if (!path || !app.connected) {
    chapters.marks = [];
    chapters.layoutCount = 0;
    chapters.forPath = path;
    return;
  }
  if (!force && chapters.forPath === path && chapters.loading) return;
  const seq = ++loadSeq;
  chapters.loading = true;
  chapters.error = '';
  try {
    const data = await api.getChapters();
    // 请求在途时又换片 / 又发了一次读取：丢弃这份过期结果
    if (currentPath() !== path || seq !== loadSeq) return;
    chapters.marks = data.marks ?? [];
    chapters.layoutCount = data.chapters?.length ?? 0;
    chapters.forPath = path;
    // 草稿指向的标记已经不在了（别的窗口删掉 / 撤销掉）：草稿一起作废
    if (chapters.draft && !chapters.marks.some((mark) => mark.id === chapters.draft?.from)) {
      chapters.draft = null;
    }
  } catch (err) {
    chapters.error = (err as Error).message;
    chapters.marks = [];
    chapters.layoutCount = 0;
  } finally {
    chapters.loading = false;
  }
}

/**
 * 整表保存（一步历史）。
 *
 * 乐观更新：先把新列表放到界面上（输入标题时不会卡），失败再回滚成服务端版本。
 */
async function persist(next: ChapterMark[], label: string): Promise<void> {
  const previous = chapters.marks;
  const path = currentPath();
  const seq = ++saveSeq;
  chapters.marks = next;
  chapters.saving = true;
  chapters.error = '';
  try {
    const data = await api.saveChapters({ marks: next, label });
    if (currentPath() !== path || seq !== saveSeq) return;
    chapters.marks = data.marks ?? next;
    chapters.layoutCount = data.chapters?.length ?? 0;
    chapters.forPath = path;
  } catch (err) {
    if (seq === saveSeq) chapters.marks = previous;
    chapters.error = (err as Error).message;
    toast(`章节标记保存失败：${(err as Error).message}`, 'error');
  } finally {
    chapters.saving = false;
  }
}

/** 章节自动命名模板（设置页可改；读不到时用默认「章节{num}」）。 */
function nameTemplate(): string {
  return normalizeTemplate(app.settings?.chapter_name_template ?? DEFAULT_CHAPTER_TEMPLATE);
}

/** 按当前模板给候选区间起名（序号只数区间章节，按起点排序）。 */
function autoName(candidate: { id?: string; start: number; end: number | null }): string {
  return autoChapterName(nameTemplate(), chapters.marks, candidate);
}

function timecode(seconds: number): string {
  const total = Math.max(0, seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** 在播放头插一个时刻点（标题为空时给一个可改的默认名）。 */
export async function addPointAtPlayhead(title = ''): Promise<void> {
  const start = Math.max(0, Math.min(play.time, play.duration || play.time));
  const mark: ChapterMark = {
    id: newId(),
    start: Math.round(start * 1000) / 1000,
    end: null,
    title: (title || '').trim() || `时刻点 ${timecode(start)}`,
  };
  await persist([...chapters.marks, mark], `新建时刻点「${mark.title}」`);
}

/** 把当前时间选区设为一个章节区间。 */
export async function addRangeChapter(
  selection: { start: number; end: number } | null,
  title = '',
): Promise<void> {
  if (!selection || selection.end - selection.start < 0.2) {
    toast('先框选一段波形，或改用「在播放头插时刻点」', 'warn');
    return;
  }
  const start = Math.round(Math.max(0, selection.start) * 1000) / 1000;
  const end = Math.round(Math.max(start + 0.2, selection.end) * 1000) / 1000;
  const id = newId();
  const mark: ChapterMark = {
    id,
    start,
    end,
    // 没给标题就按位置自动命名（章节一 / 章节二…），模板在设置里可改
    title: (title || '').trim() || autoName({ id, start, end }),
  };
  await persist([...chapters.marks, mark], `新建章节「${mark.title}」`);
}

/** 改标题 / 起止时间。`end === null` 表示改回时刻点。 */
export async function updateMark(
  id: string,
  patch: Partial<Pick<ChapterMark, 'start' | 'end' | 'title'>>,
  label = '',
): Promise<void> {
  const target = chapters.marks.find((mark) => mark.id === id);
  if (!target) return;
  const next = chapters.marks.map((mark) => (mark.id === id ? { ...mark, ...patch } : mark));
  const action = label || (patch.title !== undefined ? '重命名章节' : '调整章节时间');
  await persist(next, `${action}「${(patch.title ?? target.title) || '未命名'}」`);
}

/** 删除一条。 */
export async function removeMark(id: string): Promise<void> {
  const target = chapters.marks.find((mark) => mark.id === id);
  if (!target) return;
  if (chapters.draft?.from === id) chapters.draft = null;
  await persist(
    chapters.marks.filter((mark) => mark.id !== id),
    `删除章节「${target.title || '未命名'}」`,
  );
}

/** 点标记跳转（不自动播放：与核对台单击跳转同一口径）。 */
export function seekToMark(id: string): void {
  const target = chapters.marks.find((mark) => mark.id === id);
  if (!target) return;
  seekTo(Math.min(target.start, play.duration || target.start));
}

/**
 * 把区间章节填进转写页的两个时间输入框并切过去。
 *
 * 与核对台选区工具条的「同步到转写页」同一条链路：写一次性消息 `app.slice`，
 * 转写页读走即清空（见 `lib/transcribeSlice.ts`）。时刻点没有区间，不提供入口。
 */
export function useChapterAsTranscribe(mark: {
  id: string;
  start: number;
  end: number | null;
  title: string;
}): void {
  if (mark.end === null) return;
  app.slice = {
    start: tcShort(mark.start),
    end: tcShort(mark.end),
    nonce: (app.slice?.nonce ?? 0) + 1,
  };
  app.view = 'transcribe';
  app.inspectorOpen = false;
  toast(`已把「${mark.title || '未命名'}」填进转写页的时间区间，可直接局部转写`);
}

/** 供导出页判断「存在标记时默认开启」。 */
export function hasChapters(): boolean {
  return chapters.marks.length > 0;
}

export function clearChaptersState(): void {
  chapters.marks = [];
  chapters.layoutCount = 0;
  chapters.forPath = '';
  chapters.selection = null;
  chapters.draft = null;
}

// ---------------------------------------------------------------- 章节草稿

/**
 * 从一条时刻点开草稿。
 *
 * `edge` 是「这个时刻被当成章节的哪一端」：用户先找到场景结束就传 `end`
 * （面板上的「补起点」），先找到开始就传 `start`（「补终点」）。
 */
export function beginChapterDraft(id: string, edge: DraftEdge): void {
  const mark = chapters.marks.find((item) => item.id === id);
  if (!mark) return;
  if (mark.end !== null) {
    toast('这条已经是区间章节，直接在列表里编辑起止时间', 'warn');
    return;
  }
  chapters.draft = beginDraft({ id: mark.id, title: mark.title, time: mark.start, edge });
  const at = timecode(mark.start);
  toast(
    edge === 'end'
      ? `已把 ${at} 记作章末：缩放到起点后按 I`
      : `已把 ${at} 记作章首：缩放到终点后按 O`,
  );
}

/**
 * 用播放头时间落一端（`I` / `O` 键与草稿条上的按钮共用）。
 *
 * 没有草稿时只提示，不凭空开一份——「想补哪一端」这个决定得用户先做。
 */
export function setChapterDraftEdge(edge: DraftEdge, time: number): void {
  const draft = chapters.draft;
  if (!draft) {
    toast('先在章节面板里点「补起点 / 补终点」开一份草稿', 'warn');
    return;
  }
  const next = setEdge(draft, edge, time, play.duration || 0);
  if (next.error) {
    toast(next.error, 'warn');
    return;
  }
  chapters.draft = next.draft;
}

/** 两端齐了就按 id 原地把时刻点升级成区间；一步历史，⌘Z 可退。 */
export async function saveChapterDraft(): Promise<boolean> {
  const draft = chapters.draft;
  const error = readyError(draft);
  if (!draft || error) {
    toast(error || '章节还差一端', 'warn');
    return false;
  }
  const times = toMarkTimes(draft);
  if (!times) {
    toast('章节太短（至少 0.2 秒）', 'warn');
    return false;
  }
  const target = chapters.marks.find((mark) => mark.id === draft.from);
  if (!target) {
    chapters.draft = null;
    toast('原标记已经不存在了', 'warn');
    return false;
  }
  const renamed = isAutoTitle(target.title)
    ? autoName({ id: target.id, start: times.start, end: times.end })
    : target.title;
  const next = chapters.marks.map((mark) =>
    mark.id === draft.from ? { ...mark, start: times.start, end: times.end, title: renamed } : mark,
  );
  chapters.draft = null;
  await persist(next, `补全章节「${target.title || '未命名'}」`);
  toast(`章节已补全：${renamed}（${timecode(times.start)} → ${timecode(times.end)}）`);
  return true;
}

/** 取消草稿（Esc / 草稿条上的取消）。返回是否真的取消了一份草稿。 */
export function cancelChapterDraft(): boolean {
  if (!chapters.draft) return false;
  chapters.draft = null;
  return true;
}
