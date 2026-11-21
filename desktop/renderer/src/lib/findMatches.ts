/**
 * 查找与替换的命中计算（纯函数，从 ReviewView 抽出）。
 *
 * 屏幕上需要的东西只有四样：所有命中、被跳过的命中、当前这一处的序号、以及
 * 删除线要用的起点集合。它们全是 `{query, caseSensitive, cues, translations,
 * skipped}` 的函数，没有任何 DOM 或响应式依赖——放在 lib 里才能单测，
 * 也才能让核对台组件继续只做「渲染 + 事件」。
 */

export type FindTrack = 'source' | 'target';

export interface FindHit {
  cue: number;
  track: FindTrack;
  /** 命中在文本里的起点（字符偏移）。 */
  start: number;
  end: number;
}

/**
 * 本轮查找里被「跳过」的命中点。
 *
 * 只认 (条 / 轨 / 起点)，不写字幕、不进历史。替换掉同一句里更靠前的命中时，
 * `shiftFindAnchors` 会把后面这些锚点一起平移，跳过标记不会因为字符前移而失效。
 */
export interface FindSkipAnchor {
  cue: number;
  track: FindTrack;
  start: number;
}

/** 转义成 RegExp 字面量：查找词里的 `.` `*` 都不能当通配符。 */
export function escapeRe(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function findHitKey(hit: FindSkipAnchor): string {
  return `${hit.cue}:${hit.track}:${hit.start}`;
}

/**
 * 收集所有命中（含被跳过的）。
 *
 * `translationAt(index)` 由调用方提供：译文轨存在 `app.translations[lang]`，
 * 不是 cue 的字段；传空串表示这条没有译文。
 */
export function collectFindHits(
  cues: { text: string }[],
  tracks: FindTrack[],
  query: string,
  caseSensitive: boolean,
  translationAt: (index: number) => string,
): FindHit[] {
  const hits: FindHit[] = [];
  if (!query) return hits;
  const flags = caseSensitive ? 'g' : 'gi';
  const source = escapeRe(query);
  cues.forEach((cue, index) => {
    for (const track of tracks) {
      const text = track === 'source' ? cue.text : translationAt(index);
      if (!text) continue;
      const re = new RegExp(source, flags);
      let found: RegExpExecArray | null;
      while ((found = re.exec(text)) !== null) {
        hits.push({
          cue: index,
          track,
          start: found.index,
          end: found.index + found[0].length,
        });
        // 空匹配（例如查找词被删成空）会把 lastIndex 卡住：手动前进一格
        if (found[0].length === 0) re.lastIndex += 1;
      }
    }
  });
  return hits;
}

/** 待处理命中：跳过的不再参与上一处/下一处/替换。 */
export function filterSkippedHits(hits: FindHit[], skippedKeys: Set<string>): FindHit[] {
  if (!skippedKeys.size) return hits;
  return hits.filter((hit) => !skippedKeys.has(findHitKey(hit)));
}

/** 被跳过的命中数（查找栏的「已跳过 N 处」）。 */
export function countSkippedHits(hits: FindHit[], skippedKeys: Set<string>): number {
  let count = 0;
  for (const hit of hits) {
    if (skippedKeys.has(findHitKey(hit))) count += 1;
  }
  return count;
}

/** 某一轨里被跳过的起点，渲染删除线用；单行字幕与原文下标一致。 */
export function skippedStartsByCueTrack(
  skipped: FindSkipAnchor[],
): Map<string, Set<number>> {
  const map = new Map<string, Set<number>>();
  for (const anchor of skipped) {
    const key = `${anchor.cue}:${anchor.track}`;
    let starts = map.get(key);
    if (!starts) {
      starts = new Set();
      map.set(key, starts);
    }
    starts.add(anchor.start);
  }
  return map;
}

/**
 * 当前命中在**原始命中列表**里的序号：同一句里可能有「已跳过」的同词，
 * 只点亮当前这一处就不能用过滤后的下标。
 */
export function ordinalOfHit(rawHits: FindHit[], hit: FindHit): number {
  let ordinal = 0;
  for (const raw of rawHits) {
    if (raw.cue !== hit.cue || raw.track !== hit.track) continue;
    if (raw.start === hit.start) break;
    ordinal += 1;
  }
  return ordinal;
}

/**
 * 一条字幕文本被切成「命中 / 未命中」片段（表格每行渲染 <span> 用）。
 *
 * `track` 决定这条文本是否在当前搜索范围内：原文模式下不点亮译文行，
 * 译文模式下不点亮原文行，双语两条都点亮。`currentOrdinal` 是当前命中在这条轨里
 * 的第几个（按显示文本数），只点亮那一处；`skipped` 是本轮跳过的起点集合，
 * 用于给它们加删除线。
 */
export interface FindSegment {
  text: string;
  hit: boolean;
  /** 当前正在处理的这一处（仅一处为 true）。 */
  cur: boolean;
  /** 本轮已跳过。 */
  skipped: boolean;
}

export interface HighlightContext {
  /** 查找栏是否开着：关着就别给整表套正则。 */
  open: boolean;
  query: string;
  caseSensitive: boolean;
  /** 本次查找覆盖的轨；不在其中的轨一律不点亮。 */
  tracks: FindTrack[];
}

function plainSegment(text: string): FindSegment {
  return { text, hit: false, cur: false, skipped: false };
}

export function highlightSegments(
  text: string,
  track: FindTrack,
  currentOrdinal: number,
  skipped: Set<number> | undefined,
  ctx: HighlightContext,
): FindSegment[] {
  const query = ctx.query;
  if (!ctx.open || !query || !ctx.tracks.includes(track)) {
    return [plainSegment(text)];
  }
  const re = new RegExp(escapeRe(query), ctx.caseSensitive ? 'g' : 'gi');
  const parts: FindSegment[] = [];
  let last = 0;
  let ordinal = 0;
  let found: RegExpExecArray | null;
  while ((found = re.exec(text)) !== null) {
    if (found.index > last) parts.push(plainSegment(text.slice(last, found.index)));
    parts.push({
      text: found[0],
      hit: true,
      cur: ordinal === currentOrdinal,
      skipped: skipped?.has(found.index) ?? false,
    });
    ordinal += 1;
    last = found.index + found[0].length;
    if (found[0].length === 0) re.lastIndex += 1;
  }
  if (last < text.length) parts.push(plainSegment(text.slice(last)));
  return parts.length ? parts : [plainSegment(text)];
}
