<script lang="ts">
  /**
   * 清理标点浮层（核对台顶栏）。
   *
   * 形态取舍：不做模态确认框。这个应用里只有快捷键面板和退出确认是模态的，一个
   * 批量小操作每次弹窗会让熟练用户烦；但整表改写又需要「看得见影响范围」。所以
   * 走「按钮 → 同款下拉浮层（带统计与三条前后对比）→ 主按钮」，与「⋯ 更多」菜单
   * 同一套手感，比纯模态轻、比即点即改稳。
   *
   * 2026-11-25：支持译文轨。浮层顶部多了「清理哪一轨」，两轨都清时统计与预览
   * 分成两组（**同一套规则不可能同时适配日语与中文**，所以口径也分两组）。
   *
   * 规则与提交都在 lib 里，这个组件只负责画和键盘；`app.cues` /
   * `app.translationsRevision` 一变（应用、⌘Z、历史跳转），统计与预览会自动重算。
   */
  import Icon from './Icon.svelte';
  import {
    applyPunctClean,
    closePunctPanel,
    effectiveTracks,
    hasTranslationTrack,
    punctOptions,
    punctPanel,
    punctPlans,
    setPunctEllipsis,
    setPunctMid,
    setPunctTargetCollapse,
    setPunctTargetEllipsis,
    setPunctTracks,
    targetOptions,
  } from '../lib/punctuationPanel.svelte';
  import { markedSpans, type CleanOptions } from '../lib/punctuation';
  import { app } from '../lib/store.svelte';

  const PREVIEW_LINES = 3;

  let panelEl: HTMLDivElement | undefined = $state();

  const plans = $derived(punctPlans());
  const tracks = $derived(effectiveTracks());
  const hasTrack = $derived(hasTranslationTrack());
  const sourceCount = $derived(plans.source?.changed.length ?? 0);
  const targetCount = $derived(plans.target?.changed.length ?? 0);
  const count = $derived(sourceCount + targetCount);
  const trackLen = $derived(plans.targetTexts.length);

  interface PreviewLine {
    index: number;
    before: string;
    after: string;
    marks: { text: string; hit: boolean }[];
  }

  function previewOf(
    plan: { changed: number[]; texts: string[] } | null,
    texts: string[],
    opts: CleanOptions,
  ): PreviewLine[] {
    if (!plan) return [];
    return plan.changed.slice(0, PREVIEW_LINES).map((index) => ({
      index,
      before: texts[index] ?? '',
      after: plan.texts[index] ?? '',
      marks: markedSpans(texts[index] ?? '', opts),
    }));
  }

  const sourcePreview = $derived(previewOf(plans.source, plans.sourceTexts, punctOptions()));
  const targetPreview = $derived(
    previewOf(plans.target, plans.targetTexts, targetOptions()),
  );

  /** 把一行文本切成「普通 / 命中」的片段，供 `{#each}` 上色。 */
  function segments(text: string, hit: (ch: string) => boolean) {
    const out: { text: string; hit: boolean }[] = [];
    for (const ch of text) {
      const isHit = hit(ch);
      const last = out[out.length - 1];
      if (last && last.hit === isHit) last.text += ch;
      else out.push({ text: ch, hit: isHit });
    }
    return out;
  }

  /**
   * 「清理后」行：只给换出来的空格上色。
   * 省略号与受保护的小数点由规则层判定，组件不再自己写一份正则。
   */
  const newSegments = (text: string) => segments(text, (ch) => ch === ' ' || ch === '\u3000');

  // 浮层打开期间：点空白处关闭、Esc 关闭、Enter 直接应用（不落到「删除当前字幕」上）。
  // 用捕获阶段拦住，否则 App 的全局 Enter = 删除当前句会抢先跑掉。
  $effect(() => {
    if (!punctPanel.open) return;

    const onDown = (e: PointerEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target) return;
      if (panelEl?.contains(target)) return;
      // 触发器自己会 toggle，别在这里先关一次再被它打开
      if (target.closest('[data-punct-trigger]')) return;
      closePunctPanel();
    };

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        closePunctPanel();
        return;
      }
      if (e.key !== 'Enter' || e.metaKey || e.ctrlKey || e.altKey) return;
      // 焦点在浮层里就交给按钮 / 复选框自己处理
      const target = e.target as HTMLElement | null;
      if (target && panelEl?.contains(target)) return;
      e.preventDefault();
      e.stopPropagation();
      void applyPunctClean();
    };

    window.addEventListener('pointerdown', onDown, true);
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('pointerdown', onDown, true);
      window.removeEventListener('keydown', onKey, true);
    };
  });
</script>

{#if punctPanel.open}
  <div class="punct-panel" role="dialog" aria-label="清理标点" bind:this={panelEl}>
    <div class="pp-head">
      <span>清理标点</span>
      <button class="pp-x" onclick={closePunctPanel} title="关闭（Esc）" aria-label="关闭">
        <Icon name="close" size={10} />
      </button>
    </div>

    <div class="pp-row">
      <span class="pp-label">清理</span>
      <div class="pp-seg" role="group" aria-label="清理哪一轨">
        <button
          class:on={tracks === 'source'}
          aria-pressed={tracks === 'source'}
          title="只清原文轨（日语规则，行为和以前一样）"
          onclick={() => setPunctTracks('source')}
        >
          原文
        </button>
        <button
          class:on={tracks === 'target'}
          aria-pressed={tracks === 'target'}
          disabled={!hasTrack}
          title={hasTrack
            ? '只清当前译文轨：句中标点保留，只清行首行尾、折叠重复'
            : '还没有译文轨：先在检查器导入或应用一版译文'}
          onclick={() => setPunctTracks('target')}
        >
          译文
        </button>
        <button
          class:on={tracks === 'both'}
          aria-pressed={tracks === 'both'}
          disabled={!hasTrack}
          title={hasTrack
            ? '两轨一起清：一次提交、⌘Z 一步撤回两轨'
            : '还没有译文轨：先在检查器导入或应用一版译文'}
          onclick={() => setPunctTracks('both')}
        >
          两轨
        </button>
      </div>
    </div>

    {#if tracks !== 'target'}
      <div class="pp-split">原文 · 日语</div>
      <div class="pp-row">
        <span class="pp-label">句中</span>
        <div class="pp-seg" role="group" aria-label="句中标记处理方式">
          <button
            class:on={punctPanel.mid === 'delete'}
            aria-pressed={punctPanel.mid === 'delete'}
            title="直接删掉，不留空格（日语字幕不靠空格断句）"
            onclick={() => setPunctMid('delete')}
          >
            删掉
          </button>
          <button
            class:on={punctPanel.mid === 'half'}
            aria-pressed={punctPanel.mid === 'half'}
            title="换成一个半角空格"
            onclick={() => setPunctMid('half')}
          >
            半角空格
          </button>
          <button
            class:on={punctPanel.mid === 'full'}
            aria-pressed={punctPanel.mid === 'full'}
            title="换成一个全角空格"
            onclick={() => setPunctMid('full')}
          >
            全角空格
          </button>
        </div>
      </div>

      <div class="pp-row">
        <span class="pp-label">省略号</span>
        <div class="pp-seg" role="group" aria-label="省略号处理方式">
          <button
            class:on={punctPanel.ellipsis === 'trailing'}
            aria-pressed={punctPanel.ellipsis === 'trailing'}
            title="只清行尾的 …（句中的是语气，保留）"
            onclick={() => setPunctEllipsis('trailing')}
          >
            行尾删
          </button>
          <button
            class:on={punctPanel.ellipsis === 'all'}
            aria-pressed={punctPanel.ellipsis === 'all'}
            title="连句中的 … 一起清掉"
            onclick={() => setPunctEllipsis('all')}
          >
            全部删
          </button>
          <button
            class:on={punctPanel.ellipsis === 'keep'}
            aria-pressed={punctPanel.ellipsis === 'keep'}
            title="省略号全部保留"
            onclick={() => setPunctEllipsis('keep')}
          >
            保留
          </button>
        </div>
      </div>
    {/if}

    {#if tracks !== 'source' && hasTrack}
      <div class="pp-split">译文 · {app.trackLang}</div>
      <div class="pp-row">
        <span class="pp-label">行尾省略号</span>
        <div class="pp-seg" role="group" aria-label="译文行尾省略号处理方式">
          <button
            class:on={punctPanel.targetEllipsis}
            aria-pressed={punctPanel.targetEllipsis}
            title="行尾的 … / ... 一起清掉（句中的语气省略号无论如何都保留）"
            onclick={() => setPunctTargetEllipsis(true)}
          >
            删
          </button>
          <button
            class:on={!punctPanel.targetEllipsis}
            aria-pressed={!punctPanel.targetEllipsis}
            title="行尾省略号也保留，只清句读"
            onclick={() => setPunctTargetEllipsis(false)}
          >
            留
          </button>
        </div>
      </div>

      <div class="pp-row">
        <span class="pp-label">重复标点</span>
        <div class="pp-seg" role="group" aria-label="译文重复标点处理方式">
          <button
            class:on={punctPanel.targetCollapse}
            aria-pressed={punctPanel.targetCollapse}
            title="把连写的 ，， / 。。 / 、、 折叠成一个（问号感叹号是强调，不动）"
            onclick={() => setPunctTargetCollapse(true)}
          >
            折叠
          </button>
          <button
            class:on={!punctPanel.targetCollapse}
            aria-pressed={!punctPanel.targetCollapse}
            title="重复标点原样保留"
            onclick={() => setPunctTargetCollapse(false)}
          >
            不动
          </button>
        </div>
      </div>
    {/if}

    {#if plans.source}
      <div class="pp-stat">
        <span><b>{sourceCount}</b> 条原文会改 / 共 {app.cues.length} 条</span>
        <span class="pp-sub">行尾 {plans.source.endMarks} 处 · 句中 {plans.source.midMarks} 处</span>
      </div>
    {/if}
    {#if plans.target}
      <div class="pp-stat">
        <span><b>{targetCount}</b> 条译文会改 / 共 {trackLen} 条</span>
        <span class="pp-sub">行尾 {plans.target.endMarks} 处 · 重复 {plans.target.midMarks} 处</span>
      </div>
    {/if}

    {#if count}
      <div class="pp-preview">
        {#if sourcePreview.length}
          <div class="pp-group">原文</div>
          {#each sourcePreview as item (item.index)}
            <div class="pp-line">
              <div class="pp-old">
                {#each item.marks as seg}<span class:del={seg.hit}>{seg.text}</span>{/each}
              </div>
              <div class="pp-new">
                {#each newSegments(item.after) as seg}<span class:sp={seg.hit}>{seg.text}</span>{/each}
              </div>
            </div>
          {/each}
          {#if sourceCount > sourcePreview.length}
            <div class="pp-more">…另 {sourceCount - sourcePreview.length} 条原文</div>
          {/if}
          {#if plans.source?.skipped.length}
            <div class="pp-more">{plans.source.skipped.length} 条原文只有标点，已跳过</div>
          {/if}
        {/if}

        {#if targetPreview.length}
          <div class="pp-group">译文</div>
          {#each targetPreview as item (item.index)}
            <div class="pp-line">
              <div class="pp-old">
                {#each item.marks as seg}<span class:del={seg.hit}>{seg.text}</span>{/each}
              </div>
              <div class="pp-new">
                {#each newSegments(item.after) as seg}<span class:sp={seg.hit}>{seg.text}</span>{/each}
              </div>
            </div>
          {/each}
          {#if targetCount > targetPreview.length}
            <div class="pp-more">…另 {targetCount - targetPreview.length} 条译文</div>
          {/if}
          {#if plans.target?.skipped.length}
            <div class="pp-more">{plans.target.skipped.length} 条译文只有标点，已跳过</div>
          {/if}
        {/if}
      </div>
    {:else}
      <div class="pp-empty">
        {tracks === 'source' ? '这一轨没有需要清理的标点' : '这两轨都没有需要清理的标点'}
      </div>
    {/if}

    <div class="pp-foot">
      <span class="pp-hint">⌘Z 可一步撤回</span>
      <button class="btn tiny" onclick={closePunctPanel}>取消</button>
      <button
        class="btn tiny primary"
        disabled={!count || punctPanel.busy}
        onclick={() => void applyPunctClean()}
      >
        {punctPanel.busy ? '清理中…' : `清理 ${count} 条`}
      </button>
    </div>
  </div>
{/if}

<style>
  .punct-panel {
    position: absolute;
    top: calc(100% + 7px);
    right: 0;
    z-index: 61;
    width: 340px;
    max-height: min(640px, calc(100vh - 90px));
    overflow-y: auto;
    padding: var(--sp-3);
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 8px;
    box-shadow: var(--shadow-pop);
    -webkit-app-region: no-drag;
    animation: ppIn 140ms var(--ease);
  }
  @keyframes ppIn {
    from {
      opacity: 0;
      transform: translateY(-3px);
    }
  }
  .pp-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 12px;
    font-weight: 500;
    color: var(--text);
  }
  .pp-x {
    appearance: none;
    border: 0;
    background: transparent;
    color: var(--text-3);
    display: grid;
    place-items: center;
    width: 18px;
    height: 18px;
    border-radius: 4px;
    cursor: default;
  }
  .pp-x:hover {
    background: var(--fill);
    color: var(--text);
  }
  .pp-split {
    font-size: 11px;
    color: var(--text-3);
    padding-top: var(--sp-1);
    border-top: 1px solid var(--line-2);
  }
  .pp-split:first-of-type {
    border-top: 0;
    padding-top: 0;
  }
  .pp-row {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }
  .pp-label {
    font-size: 12px;
    color: var(--text-2);
    flex: 0 0 60px;
    white-space: nowrap;
  }
  .pp-seg {
    display: flex;
    flex: 1;
    border: 1px solid var(--line);
    border-radius: var(--rad-control);
    overflow: hidden;
  }
  .pp-seg button {
    appearance: none;
    flex: 1 1 0;
    min-width: 0;
    height: 24px;
    border: 0;
    background: transparent;
    color: var(--text-2);
    font: inherit;
    font-size: 11.5px;
    white-space: nowrap;
    cursor: default;
  }
  .pp-seg button:disabled {
    color: var(--text-3);
    opacity: 0.5;
  }
  .pp-seg button + button {
    border-left: 1px solid var(--line);
  }
  .pp-seg button.on {
    background: var(--control-on);
    color: var(--on-accent);
  }
  .pp-stat {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--sp-2);
    font-size: 12px;
    color: var(--text-2);
    padding-top: var(--sp-1);
    border-top: 1px solid var(--line-2);
  }
  .pp-stat b {
    font-size: 14px;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .pp-sub {
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .pp-preview {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding: var(--sp-2);
    border-radius: 6px;
    background: var(--fill);
  }
  .pp-group {
    font-size: 11px;
    color: var(--text-3);
  }
  .pp-line {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }
  /* 字幕文本按全角排：预览用字幕字体，空格的位置才看得出来 */
  .pp-old,
  .pp-new {
    font-family: var(--font-cue);
    font-size: 13px;
    line-height: 18px;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .pp-old {
    color: var(--text-3);
  }
  .pp-new {
    color: var(--text);
  }
  /* 要删掉的标点：染色 + 浅底。不加删除线——`、` `。` 这类全角标点本身就有斜笔，
     叠一条删除线会变成一坨看不懂的划痕。 */
  .del {
    color: var(--warn);
    background: var(--warn-soft);
    border-radius: 2px;
  }
  /* 换出来的那个空格：浅底标出来，否则一空格宽几乎看不见 */
  .sp {
    background: var(--accent-soft);
    border-radius: 2px;
  }
  .pp-new::before {
    content: '→';
    color: var(--text-3);
    margin-right: var(--sp-1);
  }
  .pp-more {
    font-size: 11px;
    color: var(--text-3);
  }
  .pp-empty {
    font-size: 12px;
    color: var(--text-3);
    padding: var(--sp-2) 0;
  }
  .pp-foot {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding-top: var(--sp-1);
    border-top: 1px solid var(--line-2);
  }
  .pp-hint {
    flex: 1;
    font-size: 11px;
    color: var(--text-3);
  }
  .tiny {
    height: 22px;
    font-size: 12px;
    padding: 0 7px;
    background: var(--raise);
  }
  .btn.primary.tiny {
    background: var(--btn-primary-bg);
    color: var(--on-accent);
  }
</style>
