/**
 * 核对台查找 / 替换的一整轮会话（⌘F，覆盖原文 / 译文 / 双语）。
 *
 * 从 `views/ReviewView.svelte` 搬出（红线 11 + Step 4.1 纯结构拆分）：
 * 命中计算、跳过锚点、当前处、替换 / 全部替换与焦点都收在这里；
 * 视图只负责把 `bindInput` 接到输入框，并把 `tableProps()` 交给 ReviewTable。
 *
 * 纯计算仍在 `lib/findMatches.ts`（可单测）；这里只持有「本轮」状态：
 * 跳过了哪些、当前位置、是否正在提交。关掉查找栏即结束本轮。
 */

import { tick } from 'svelte';
import {
  app,
  findState,
  jumpToCue,
  replaceAllInTracks,
  replaceInCue,
  replaceInTranslation,
  toast,
  translationTextAt,
} from './store.svelte';
import { comboOf, formatCombo } from './shortcuts.svelte';
import {
  collectFindHits,
  countSkippedHits,
  filterSkippedHits,
  findHitKey,
  highlightSegments,
  ordinalOfHit,
  skippedStartsByCueTrack,
  type FindHit,
  type FindSkipAnchor,
  type FindTrack,
} from './findMatches';

export function createReviewFind() {
  let input = $state<HTMLInputElement | null>(null);
  /** 正在提交单处替换：挡住连点，避免两个 patch 请求把 pos 抢乱。 */
  let busy = $state(false);
  let skipped = $state<FindSkipAnchor[]>([]);

  /**
   * 搜索范围跟随当前显示模式：原文只搜原文、译文只搜译文、双语两条都搜。
   * 双语里同一个词可能同时命中上下两行，所以命中记录必须带 track，替换时
   * 才能改对那张表（原文进 review_cues，译文进 translations[lang]）。
   */
  const tracks = $derived<FindTrack[]>(
    app.track === 'target' ? ['target'] : app.track === 'both' ? ['source', 'target'] : ['source'],
  );

  /** 所有命中（含已跳过）：记录属于第几条 / 哪条轨 / 在文本里的起止。 */
  const rawMatches = $derived(
    collectFindHits(app.cues, tracks, findState.query, findState.caseSensitive, translationTextAt),
  );

  const skippedKeys = $derived(new Set(skipped.map(findHitKey)));
  /** 待处理命中：跳过的不再参与上一处/下一处/替换，本轮到它就直接略过。 */
  const matches = $derived(filterSkippedHits(rawMatches, skippedKeys));
  const skippedCount = $derived(
    skipped.length ? countSkippedHits(rawMatches, skippedKeys) : 0,
  );
  /** 某一轨里被跳过的起点，渲染删除线用；单行字幕与原文下标一致。 */
  const skippedStarts = $derived(skippedStartsByCueTrack(skipped));

  const matchedCues = $derived(
    new Set((findState.open ? matches : []).map((hit) => hit.cue)),
  );

  /** 当前这一处（未跳过的）在原始命中里的序号，用来只点亮同一个词里的那一处。 */
  const current = $derived.by(() => {
    if (!findState.open) return null;
    const hit = matches[findState.pos];
    if (!hit) return null;
    return { ...hit, ordinal: ordinalOfHit(rawMatches, hit) };
  });

  const prevKey = $derived(formatCombo(comboOf('review.findPrev')));
  const nextKey = $derived(formatCombo(comboOf('review.findNext')));

  function resetSession() {
    skipped = [];
    findState.pos = 0;
  }

  function bindInput(node: HTMLInputElement | null) {
    input = node;
  }

  $effect(() => {
    const nonce = findState.focusNonce;
    void nonce;
    if (!findState.open) return;
    void tick().then(() => {
      input?.focus();
      input?.select();
    });
  });

  // 关掉查找栏就结束「本轮」：下次重开时不记得上一轮跳过过谁。
  $effect(() => {
    if (!findState.open && skipped.length) skipped = [];
  });

  // 原文 / 译文 / 双语切换会改变搜索范围，旧的跳过锚点不再对应同一批命中。
  let lastTracksKey = '';
  $effect(() => {
    const key = tracks.join(',');
    if (key === lastTracksKey) return;
    const firstRun = !lastTracksKey;
    lastTracksKey = key;
    if (!firstRun) resetSession();
  });

  // 替换 / 跳过之后匹配数会变少：把当前位置拉回合法范围
  $effect(() => {
    const total = matches.length;
    if (total === 0) {
      if (findState.pos !== 0) findState.pos = 0;
      return;
    }
    if (findState.pos >= total) findState.pos = 0;
  });

  /**
   * 替换掉某条字幕里的一处命中后，同一轨后面那些跳过锚点的起点会整体左/右移。
   * 不平移的话，被跳过的逗号会因为前一个逗号被删掉而“复活”。
   */
  function shiftAnchors(
    cue: number,
    track: FindTrack,
    at: number,
    removed: number,
    inserted: number,
  ) {
    if (!skipped.length) return;
    const delta = inserted - removed;
    if (!delta) return;
    let changed = false;
    const next = skipped.map((anchor) => {
      if (anchor.cue !== cue || anchor.track !== track) return anchor;
      if (anchor.start <= at) return anchor;
      changed = true;
      return { ...anchor, start: Math.max(at, anchor.start + delta) };
    });
    if (changed) skipped = next;
  }

  function revealHit(hit: FindHit | undefined) {
    if (!hit) return;
    jumpToCue(hit.cue);
  }

  /**
   * 整批替换未跳过的命中以后，同一轨里被跳过的字符会随前面的删/插整体平移。
   * 按替换前的未跳过命中累计位移，把跳过锚点搬到新位置，删除线才不会消失。
   */
  function reseatSkippedAfterReplaceAll(hits: FindHit[], inserted: number) {
    if (!skipped.length) return;
    const byTrack = new Map<string, FindHit[]>();
    for (const hit of hits) {
      const key = `${hit.cue}:${hit.track}`;
      let list = byTrack.get(key);
      if (!list) {
        list = [];
        byTrack.set(key, list);
      }
      list.push(hit);
    }
    skipped = skipped.map((anchor) => {
      let shift = 0;
      for (const hit of byTrack.get(`${anchor.cue}:${anchor.track}`) ?? []) {
        if (hit.start < anchor.start) shift += inserted - (hit.end - hit.start);
      }
      return shift ? { ...anchor, start: Math.max(0, anchor.start + shift) } : anchor;
    });
  }

  function go(delta: number) {
    if (busy) return;
    const total = matches.length;
    if (!total) {
      toast(
        rawMatches.length
          ? '本轮匹配都已跳过，改一下查找词可以重新开始'
          : '没有找到匹配的文本',
        'warn',
      );
      return;
    }
    findState.pos = (findState.pos + delta + total) % total;
    revealHit(matches[findState.pos]);
  }

  async function replaceCurrent() {
    if (!findState.query || busy) return;
    const total = matches.length;
    if (!total) {
      toast(
        rawMatches.length
          ? '本轮匹配都已跳过，改一下查找词可以重新开始'
          : '没有可替换的匹配',
        'warn',
      );
      return;
    }
    const hit = matches[Math.min(findState.pos, total - 1)];
    if (!hit) return;
    const posBefore = findState.pos;
    const query = findState.query;
    const replacement = findState.replacement;
    const caseSensitive = findState.caseSensitive;
    const removed = hit.end - hit.start;
    busy = true;
    try {
      const ok =
        hit.track === 'source'
          ? await replaceInCue(hit.cue, query, replacement, caseSensitive, hit.start)
          : await replaceInTranslation(hit.cue, query, replacement, caseSensitive, hit.start);
      if (!ok) return;
      const where = hit.track === 'source' ? '原文' : '译文';
      // 请求期间用户把查找栏关了：替换照常生效，但不要再抢选中/滚动。
      if (!findState.open) {
        toast(`已替换 1 处${where}`);
        return;
      }
      // 请求期间用户改了查找条件：替换已经发生，但不要拿旧位置继续前进。
      if (findState.query !== query || findState.caseSensitive !== caseSensitive) {
        toast(`已替换 1 处${where}`);
        return;
      }
      // 被替换的命中已经从数组消失，后面的跳过锚点要跟着平移。
      shiftAnchors(hit.cue, hit.track, hit.start, removed, replacement.length);
      const left = matches.length;
      if (!left) {
        findState.pos = 0;
        // 还有没被替换的命中，说明它们都已经标记跳过了，不能因为“没得替换”就清标记。
        if (!rawMatches.length) skipped = [];
        toast(
          rawMatches.length
            ? '已替换完最后一处待处理匹配，其余都已跳过'
            : '已替换最后一处，本轮没有待处理匹配了',
        );
        return;
      }
      let wrapped = false;
      if (posBefore >= left) {
        findState.pos = 0;
        wrapped = true;
      } else {
        findState.pos = Math.min(posBefore, left - 1);
      }
      revealHit(matches[findState.pos]);
      toast(`已替换 1 处${where}${wrapped ? '，已回到第一处' : ''}`);
    } finally {
      busy = false;
    }
  }

  /** 跳过当前这一处：不写字幕、不进历史，本轮不再回到它。 */
  function skip() {
    if (!findState.query || busy) return;
    const total = matches.length;
    if (!total) {
      toast(
        rawMatches.length
          ? '本轮匹配都已跳过，改一下查找词可以重新开始'
          : '没有可跳过的匹配',
        'warn',
      );
      return;
    }
    const hit = matches[Math.min(findState.pos, total - 1)];
    if (!hit) return;
    const posBefore = findState.pos;
    const key = findHitKey(hit);
    if (!skippedKeys.has(key)) {
      skipped = [...skipped, { cue: hit.cue, track: hit.track, start: hit.start }];
    }
    const left = matches.length;
    if (!left) {
      toast('已跳过最后一处，本轮没有待处理匹配了');
      return;
    }
    let wrapped = false;
    if (posBefore >= left) {
      findState.pos = 0;
      wrapped = true;
    } else {
      findState.pos = Math.min(posBefore, left - 1);
    }
    revealHit(matches[findState.pos]);
    toast(`已跳过 1 处，本轮剩余 ${left} 处${wrapped ? '（已回到第一处）' : ''}`);
  }

  async function replaceAll() {
    if (!findState.query || busy) return;
    const query = findState.query;
    const replacement = findState.replacement;
    const caseSensitive = findState.caseSensitive;
    const activeBefore = matches.slice();
    busy = true;
    try {
      // 原文 + 译文一次提交：双语模式下只压一步历史，⌘Z 一次退干净。
      const counts = await replaceAllInTracks(
        query,
        replacement,
        caseSensitive,
        tracks,
        skippedKeys,
      );
      const count = counts.source + counts.target;
      if (!count) {
        toast(
          skippedCount ? '剩余命中都已跳过，没有可替换的' : '没有找到匹配的文本',
          'warn',
        );
        return;
      }
      findState.pos = 0;
      // 请求期间用户改了查找条件：跳过集合已经被重置，不要再用旧位移去搬。
      if (findState.query === query && findState.caseSensitive === caseSensitive) {
        reseatSkippedAfterReplaceAll(activeBefore, replacement.length);
      }
      const kept = skippedCount;
      const detail =
        counts.source && counts.target
          ? `（原文 ${counts.source} / 译文 ${counts.target}）`
          : counts.target
            ? '（译文）'
            : '';
      toast(`已替换 ${count} 处${detail}${kept ? `，跳过 ${kept} 处保持原样` : ''}`);
    } finally {
      busy = false;
    }
  }

  /** 切片逻辑在 lib/findMatches（纯函数），这里只把当前的查找上下文接进来。 */
  function highlight(
    text: string,
    track: FindTrack,
    currentOrdinal: number,
    skippedStarts?: Set<number>,
  ) {
    return highlightSegments(text, track, currentOrdinal, skippedStarts, {
      open: findState.open,
      query: findState.query,
      caseSensitive: findState.caseSensitive,
      tracks,
    });
  }

  /** 当前命中在这条 cue / 这条轨里的序号；不是当前行返回 -1。 */
  function ordinalFor(index: number, track: FindTrack): number {
    const cur = current;
    if (!cur || cur.cue !== index || cur.track !== track) return -1;
    return cur.ordinal;
  }

  function skippedFor(index: number, track: FindTrack): Set<number> | undefined {
    return skippedStarts.get(`${index}:${track}`);
  }

  return {
    bindInput,
    resetSession,
    go,
    replaceCurrent,
    skip,
    replaceAll,
    highlight,
    ordinalFor,
    skippedFor,
    get busy() {
      return busy;
    },
    get tracks() {
      return tracks;
    },
    get rawMatches() {
      return rawMatches;
    },
    get matches() {
      return matches;
    },
    get skippedCount() {
      return skippedCount;
    },
    get matchedCues() {
      return matchedCues;
    },
    get current() {
      return current;
    },
    get prevKey() {
      return prevKey;
    },
    get nextKey() {
      return nextKey;
    },
  };
}
